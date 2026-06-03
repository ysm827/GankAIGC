"""
朱雀AI检测 API — CDP浏览器桥接版 (v2 实战验证)
原理: Chrome CDP (9223) → matrix.tencent.com/ai-detect/ → UI自动化检测
已验证流程: 清空→点击示例SPAN初始化→替换textarea文本→点击检测→轮询Vue结果
优势: 无需验证码票据, 使用浏览器已有JWT登录态
"""

import json
import asyncio
import websockets
import urllib.request
import time
from typing import Optional, Dict, Any


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 检测结果标签
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LABEL_NAMES = {
    0: "AI生成",
    1: "人工编写", 
    2: "混合/可疑"
}

LABEL_EMOJI = {
    0: "🤖",
    1: "✍️",
    2: "⚠️"
}


class ZhuqueAPI:
    """通过Chrome CDP控制朱雀检测页面, 实现完整检测流程"""

    def __init__(self, cdp_port: int = 9223, debug: bool = False):
        self.cdp_port = cdp_port
        self.debug = debug
        self._seq = 0

    # ── 内部: CDP WebSocket ──────────────────────────────

    async def _cdp_connect(self):
        """获取matrix.tencent.com标签的CDP WebSocket"""
        try:
            tabs = json.loads(urllib.request.urlopen(
                f'http://127.0.0.1:{self.cdp_port}/json/list', timeout=5
            ).read())
        except Exception as e:
            raise RuntimeError(
                f"无法连接Chrome CDP端口 {self.cdp_port}。"
                f"请确保Chrome以 --remote-debugging-port={self.cdp_port} 启动"
            ) from e

        for t in tabs:
            if 'matrix.tencent.com' in t.get('url', ''):
                return t['webSocketDebuggerUrl']

        raise RuntimeError(
            "未找到matrix.tencent.com标签页。请先在Chrome打开:\n"
            "  https://matrix.tencent.com/ai-detect/"
        )

    async def _eval(self, ws, js: str, timeout: float = 15.0) -> Any:
        """在浏览器中执行JS, 返回结果值"""
        self._seq += 1
        await ws.send(json.dumps({
            "id": self._seq,
            "method": "Runtime.evaluate",
            "params": {
                "expression": js,
                "returnByValue": True,
                "awaitPromise": True,
            }
        }))
        # 读取响应 (可能有中间消息如 Page.frameStoppedLoading)
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.time())
            msg = json.loads(raw)
            if msg.get('id') == self._seq:
                result = msg.get('result', {})
                if 'exceptionDetails' in result:
                    err = result['exceptionDetails']
                    raise RuntimeError(
                        f"JS异常: {err.get('text', '')} | {err.get('exception', {}).get('description', '')}"
                    )
                return result.get('result', {}).get('value', None)
        raise TimeoutError(f"CDP _eval 超时 ({timeout}s)")

    # ── 公开API: 状态检查 ─────────────────────────────────

    async def status(self) -> dict:
        """检查浏览器页面状态"""
        cdp_ws = await self._cdp_connect()
        async with websockets.connect(cdp_ws, max_size=2**24) as ws:
            info = await self._eval(ws, """
                JSON.stringify({
                    url: location.href,
                    has_token: !!localStorage.getItem('aiGenAccessToken'),
                    token_preview: (localStorage.getItem('aiGenAccessToken')||'').substring(0,60),
                    btn_text: (function(){
                        var b = document.querySelector('.submit-btn');
                        return b ? b.textContent.trim() : 'NOT FOUND';
                    })(),
                    textarea_len: (function(){
                        var t = document.querySelector('.el-textarea__inner');
                        return t ? t.value.length : -1;
                    })(),
                    result_visible: !!document.querySelector('.ai-detection-result'),
                })
            """)
            return json.loads(info)

    # ── 公开API: 文本检测 ─────────────────────────────────

    async def detect(self, text: str, timeout: float = 60.0) -> dict:
        """
        检测文本是否为AI生成。

        Args:
            text: 待检测文本 (>350字, 建议400-3000字)
            timeout: 超时秒数 (检测服务可能较慢)

        Returns:
            {
                "success": True/False,
                "rate": 0-100,           # AI浓度百分比 (越高越像AI)
                "rate_label": str,        # 如 "嗅探到AI浓度"
                "labels_ratio": {0: AI概率, 1: 人类概率, 2: 混合概率},
                "alert_text": str,        # 人类可读判定, 如 "未发现明显的人工创作特征"
                "alert_title": str,       # 提示信息
                "message": str,           # 额外消息
                "remaining_uses": int,    # 剩余检测次数
                "text_length": int,       # 实际检测文本长度
            }
        """
        text_len = len(text)
        if text_len < 350:
            return {
                "success": False,
                "message": f"文本长度不足 ({text_len}<350字), 请提供更长的文本",
                "rate": 0, "rate_label": "", "labels_ratio": {},
                "alert_text": "", "alert_title": "", "remaining_uses": -1,
                "text_length": text_len,
            }

        cdp_ws = await self._cdp_connect()
        async with websockets.connect(cdp_ws, max_size=2**24) as ws:
            # Step 1: 点击"清空"按钮, 确保处于输入模式
            await self._eval(ws, """
                (function(){
                    var btns = document.querySelectorAll('button');
                    for (var b of btns) {
                        if (b.textContent.includes('清空')) { b.click(); return 'cleared'; }
                    }
                    return 'no_clear_btn';
                })()
            """)
            await asyncio.sleep(0.3)

            # Step 2: 点击任意示例SPAN初始化textarea (唤醒Vue组件)
            await self._eval(ws, """
                (function(){
                    var spans = document.querySelectorAll('span.example');
                    if (spans.length > 2) {
                        spans[2].click();  // 示例三：人工编写文本 (较短, 便于替换)
                        return 'CLICKED_SPAN';
                    }
                    return 'NO_SPAN';
                })()
            """)
            await asyncio.sleep(0.5)

            # Step 3: 替换textarea文本 (原生setter + input事件 → Vue感知)
            escaped_text = json.dumps(text)  # JSON安全的转义
            await self._eval(ws, f"""
                (function(){{
                    var ta = document.querySelector('.el-textarea__inner');
                    if (!ta) return 'NO_TEXTAREA';
                    var setter = Object.getOwnPropertyDescriptor(
                        HTMLTextAreaElement.prototype, 'value'
                    ).set;
                    setter.call(ta, {escaped_text});
                    ta.dispatchEvent(new Event('input', {{bubbles: true}}));
                    return 'SET:' + ta.value.length;
                }})()
            """)
            await asyncio.sleep(0.3)

            # Step 4: 点击"立即检测"
            btn_check = await self._eval(ws, """
                (function(){
                    var btns = document.querySelectorAll('button');
                    for (var b of btns) {
                        if (b.textContent.includes('立即检测')) {
                            if (b.disabled) return 'DISABLED';
                            b.click();
                            return 'CLICKED';
                        }
                    }
                    return 'NOT_FOUND';
                })()
            """)
            if 'NOT_FOUND' in str(btn_check):
                raise RuntimeError("找不到检测按钮")
            if 'DISABLED' in str(btn_check):
                raise RuntimeError("检测按钮被禁用 (文本长度不足或次数用尽)")

            if self.debug:
                print(f"  [detect] 按钮状态: {btn_check}, 文本长度: {text_len}")

            # Step 5: 轮询结果
            start = time.time()
            last_result = None
            while time.time() - start < timeout:
                await asyncio.sleep(1.0)

                poll_js = """
                (function(){
                    var el = document.querySelector('.ai-detection-result');
                    if (!el || !el.__vue__) return JSON.stringify({s:'no_result'});

                    var v = el.__vue__;
                    if (v.type && !v.processing) {
                        // 检测完成
                        var alert_el = document.querySelector('.el-alert__description');
                        var alert_title = document.querySelector('.el-alert__title');
                        var remaining_el = document.querySelector('.submit-btn');
                        return JSON.stringify({
                            s: 'done',
                            rate: v.rate,
                            rateLabel: v.rateLabel,
                            labelsRatio: v.labelsRatio,
                            msg: v.msg || '',
                            type: v.type,
                            alert: alert_el ? alert_el.textContent.trim() : '',
                            alert_title: alert_title ? alert_title.textContent.trim() : '',
                            remaining_text: remaining_el ? remaining_el.textContent.trim() : '',
                        });
                    } else if (v.type === 'error') {
                        return JSON.stringify({s:'error', msg: v.msg});
                    } else {
                        return JSON.stringify({s:'processing'});
                    }
                })()
                """
                raw = await self._eval(ws, poll_js)
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if self.debug and data.get('s') != last_result:
                    print(f"  [poll] {data.get('s')}")
                    last_result = data.get('s')

                if data.get('s') == 'done':
                    # 解析剩余次数
                    remaining = -1
                    rt = data.get('remaining_text', '')
                    import re
                    m = re.search(r'(\d+)', rt or '')
                    if m:
                        remaining = int(m.group(1))

                    return {
                        "success": True,
                        "rate": data.get('rate', 0),
                        "rate_label": data.get('rateLabel', ''),
                        "labels_ratio": data.get('labelsRatio', {}),
                        "alert_text": data.get('alert', '').split('\n')[0].replace('下载报告', '').strip(),
                        "alert_title": data.get('alert_title', ''),
                        "message": data.get('msg', ''),
                        "remaining_uses": remaining,
                        "text_length": text_len,
                    }

                if data.get('s') == 'error':
                    return {
                        "success": False,
                        "message": data.get('msg', '检测服务返回错误'),
                        "rate": 0, "rate_label": "", "labels_ratio": {},
                        "alert_text": "", "alert_title": "",
                        "remaining_uses": -1, "text_length": text_len,
                    }

                # 也检查alert (有时Vue数据未更新但alert已出现)
                alert_check = await self._eval(ws, """
                    (function(){
                        var a = document.querySelector('.el-alert__description');
                        if (!a) return null;
                        var txt = a.textContent.trim();
                        if (txt.includes('too_short') || txt.includes('350')) return 'short';
                        if (txt.includes('人工') || txt.includes('AI') || txt.includes('未发现')) return txt;
                        return null;
                    })()
                """)
                if alert_check and alert_check != 'null' and alert_check != 'short':
                    # 有些结果先出现在alert中, 再获取完整Vue数据
                    continue

            # 超时
            return {
                "success": False,
                "message": f"检测超时 ({timeout}s), 请检查浏览器页面状态",
                "rate": 0, "rate_label": "", "labels_ratio": {},
                "alert_text": "", "alert_title": "",
                "remaining_uses": -1, "text_length": text_len,
            }

    # ── 便捷: 获取判定结论 ────────────────────────────────

    async def classify(self, text: str) -> dict:
        """
        简化版: 返回 'AI_generated' / 'human_written' / 'mixed' 三分类
        + 详细数据
        """
        result = await self.detect(text)
        if not result['success']:
            return {"verdict": "error", "detail": result['message'], "raw": result}

        rate = result['rate']
        alert = result['alert_text']
        ratio = result['labels_ratio']

        # 从alert或rate推断分类
        if '未发现' in alert and '人工' in alert:
            verdict = 'AI_generated'  # "未发现明显的人工创作特征" → AI
        elif '人工创作特征较弱' in alert:
            verdict = 'human_written'
        elif ratio:
            # 用labelsRatio: key 1 是"人工", key 0 是"AI"
            human_prob = float(ratio.get('1', 0))
            ai_prob = float(ratio.get('0', 0))
            if ai_prob > human_prob:
                verdict = 'AI_generated'
            elif human_prob > ai_prob:
                verdict = 'human_written'
            else:
                verdict = 'mixed'
        else:
            verdict = 'uncertain'

        return {
            "verdict": verdict,
            "verdict_label": LABEL_NAMES.get(
                0 if verdict == 'AI_generated' else (1 if verdict == 'human_written' else 2),
                verdict
            ),
            "confidence": rate / 100.0,
            "detail": alert,
            "raw": result,
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 命令行入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def main():
    import sys, argparse

    parser = argparse.ArgumentParser(
        description='朱雀AI检测API — CDP浏览器桥接版',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python zhuque_api.py --status              # 检查浏览器状态
  python zhuque_api.py "要检测的文本"         # 检测文本
  python zhuque_api.py -f test.txt           # 从文件读取
  python zhuque_api.py --classify "文本"     # 简洁分类
        """
    )
    parser.add_argument('text', nargs='?', help='待检测文本 (默认从stdin读取)')
    parser.add_argument('-f', '--file', help='从文件读取文本')
    parser.add_argument('-p', '--port', type=int, default=9223, help='Chrome CDP端口 (默认9223)')
    parser.add_argument('--status', action='store_true', help='仅检查状态')
    parser.add_argument('--classify', action='store_true', help='仅输出分类结果')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    parser.add_argument('-o', '--output', help='输出JSON到文件')
    args = parser.parse_args()

    api = ZhuqueAPI(cdp_port=args.port, debug=args.debug)

    if args.status:
        try:
            s = await api.status()
            print(json.dumps(s, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"❌ 状态检查失败: {e}")
        return

    # 获取文本
    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        print("请输入待检测文本 (Ctrl+D 结束):")
        text = sys.stdin.read()

    if not text.strip():
        print("❌ 文本为空")
        return

    text = text.strip()
    print(f"📝 文本长度: {len(text)} 字")
    print(f"⏳ 检测中...")

    try:
        if args.classify:
            result = await api.classify(text)
        else:
            result = await api.detect(text)

        # 输出
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"✅ 结果已写入 {args.output}")

        if args.classify:
            emoji = LABEL_EMOJI.get(
                0 if result['verdict'] == 'AI_generated' else
                (1 if result['verdict'] == 'human_written' else 2),
                ''
            )
            print(f"\n{'='*50}")
            print(f"  {emoji} 判定: {result['verdict_label']}")
            print(f"  置信度: {result['confidence']:.1%}")
            print(f"  详情: {result['detail']}")
            print(f"{'='*50}")
        else:
            if result['success']:
                print(f"\n{'='*50}")
                print(f"  🎯 AI浓度: {result['rate']:.1f}%")
                print(f"  📊 标签比例: AI={result['labels_ratio'].get('0', '?')}, "
                      f"人类={result['labels_ratio'].get('1', '?')}, "
                      f"混合={result['labels_ratio'].get('2', '?')}")
                print(f"  📋 判定: {result['alert_text']}")
                if result['remaining_uses'] >= 0:
                    print(f"  🔢 剩余次数: {result['remaining_uses']}")
                print(f"{'='*50}")
            else:
                print(f"❌ 检测失败: {result['message']}")

    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        if args.debug:
            traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(main())

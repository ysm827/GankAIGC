import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import { ArrowLeft, History, Loader2, Receipt, Sparkles } from 'lucide-react';
import { userAPI } from '../api';
import BrandLogo from '../components/BrandLogo';
import BeerIcon from '../components/BeerIcon';
import { formatChinaDateTime } from '../utils/dateTime';

const formatBeerDelta = (delta) => {
  const value = Number(delta || 0);
  return `${value > 0 ? '+' : ''}${value} 啤酒`;
};

const getTransactionAmountClass = (transaction) => {
  if (transaction.transaction_type === 'credit' || transaction.delta > 0) {
    return 'aurora-amount-credit';
  }
  if (transaction.transaction_type === 'debit' || transaction.delta < 0) {
    return 'aurora-amount-debit';
  }
  return 'aurora-amount-neutral';
};

const CreditsPage = () => {
  const [credits, setCredits] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(true);
  const [redeeming, setRedeeming] = useState(false);

  const loadData = async () => {
    const [creditResponse, transactionResponse] = await Promise.all([
      userAPI.getCredits(),
      userAPI.listCreditTransactions(),
    ]);
    setCredits(creditResponse.data);
    setTransactions(transactionResponse.data);
  };

  useEffect(() => {
    setLoading(true);
    loadData()
      .catch((error) => {
        console.error('加载啤酒数据失败:', error);
        toast.error('加载啤酒数据失败');
      })
      .finally(() => setLoading(false));
  }, []);

  const handleRedeem = async (event) => {
    event.preventDefault();
    if (!code.trim() || redeeming) return;

    setRedeeming(true);
    try {
      await userAPI.redeemCode(code.trim());
      setCode('');
      toast.success('兑换成功');
      await loadData();
    } catch (error) {
      toast.error(error.response?.data?.detail || '兑换失败');
    } finally {
      setRedeeming(false);
    }
  };

  return (
    <div className="gank-app-page aurora-app-page aurora-account-page">
      <div className="gank-ambient-orb orb-one" />
      <div className="gank-ambient-orb orb-two" />
      <div className="gank-ambient-orb orb-three" />

      <header className="sticky top-0 z-50">
        <nav className="apple-global-nav aurora-topbar">
          <div className="mx-auto flex min-h-[68px] max-w-[1280px] items-center justify-between gap-4 px-5 sm:px-8 lg:px-10">
            <BrandLogo size="md" showText className="aurora-brand-logo" />
            <Link to="/workspace" className="aurora-account-back-link">
              <ArrowLeft className="h-4 w-4" />
              <span>返回工作台</span>
            </Link>
          </div>
        </nav>
      </header>

      <main className="aurora-page-shell aurora-account-shell relative z-[1] mx-auto max-w-[1280px] px-5 pb-12 pt-8 sm:px-8 lg:px-10">
        <section className="aurora-account-hero">
          <div>
            <p className="gank-eyebrow">BEER BALANCE</p>
            <h1>平台啤酒</h1>
            <p>啤酒用于论文润色、增强和降重调用。1 啤酒约处理 1000 个非空白字符，流水会在这里留痕。</p>
          </div>
          <div className="aurora-account-chip-strip" aria-label="啤酒计费说明">
            <span className="apple-config-chip">Recharge</span>
            <span className="apple-config-chip">Ledger</span>
            <span className="apple-config-chip">Usage</span>
          </div>
        </section>

        <div className="grid gap-5 lg:grid-cols-[0.9fr_1.35fr]">
          <section className="apple-utility-card aurora-account-card aurora-credit-card">
            <div className="aurora-credit-hero-icon" aria-hidden="true">
              <BeerIcon className="h-10 w-10" />
            </div>
            <p className="gank-eyebrow">CURRENT BALANCE</p>
            <h2>{credits?.is_unlimited ? '无限啤酒' : credits?.credit_balance ?? '-'}</h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">当前账号可用额度，用于平台模型处理任务。</p>

            <div className="aurora-credit-rules">
              <div>
                <Sparkles className="h-4 w-4" />
                <span>润色与增强按实际字符计费</span>
              </div>
              <div>
                <Receipt className="h-4 w-4" />
                <span>兑换和扣费都会写入流水</span>
              </div>
            </div>

            <form onSubmit={handleRedeem} className="mt-6 space-y-3">
              <label className="aurora-field-label" htmlFor="redeem-code">兑换码</label>
              <input
                id="redeem-code"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder="输入兑换码"
                className="aurora-input"
              />
              <button
                type="submit"
                disabled={!code.trim() || redeeming}
                className="aurora-account-primary apple-action-pill w-full disabled:cursor-not-allowed disabled:opacity-60"
              >
                {redeeming ? <Loader2 className="h-4 w-4 animate-spin" /> : <BeerIcon className="h-4 w-4" />}
                兑换啤酒
              </button>
            </form>
          </section>

          <section className="apple-utility-card aurora-account-card aurora-ledger-card">
            <div className="aurora-ledger-head">
              <div>
                <p className="gank-eyebrow">TRANSACTION LEDGER</p>
                <h2>啤酒流水</h2>
              </div>
              <span className="aurora-subtle-badge">最近 {transactions.length} 条</span>
            </div>

            {loading ? (
              <div className="aurora-empty-state">
                <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
                <span>加载流水...</span>
              </div>
            ) : transactions.length === 0 ? (
              <div className="aurora-empty-state">
                <History className="h-5 w-5 text-slate-400" />
                <span>暂无流水记录</span>
              </div>
            ) : (
              <div className="aurora-ledger-list custom-scrollbar">
                {transactions.map((transaction) => (
                  <article key={transaction.id} className="aurora-ledger-item">
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-slate-950">{transaction.reason_label || transaction.reason}</p>
                      <p className="mt-1 text-xs font-medium text-slate-500">{formatChinaDateTime(transaction.created_at)}</p>
                      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                        <span className="aurora-ledger-chip">余额 {transaction.balance_after} 啤酒</span>
                        {transaction.related_session_title && (
                          <span className="aurora-ledger-chip">任务：{transaction.related_session_title}</span>
                        )}
                        {transaction.related_session_public_id && !transaction.related_session_title && (
                          <span className="aurora-ledger-chip">会话：{transaction.related_session_public_id.slice(0, 8)}…</span>
                        )}
                        {transaction.related_code_id && (
                          <span className="aurora-ledger-chip">兑换码 #{transaction.related_code_id}</span>
                        )}
                      </div>
                    </div>
                    <div className={`aurora-ledger-amount ${getTransactionAmountClass(transaction)}`}>
                      {formatBeerDelta(transaction.delta)}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
};

export default CreditsPage;

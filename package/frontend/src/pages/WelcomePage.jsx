import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle,
  FileText,
  Github,
  KeyRound,
  LogIn,
  Shield,
  ShieldCheck,
  Sparkles,
  Star,
  UserPlus,
} from 'lucide-react';
import BrandLogo from '../components/BrandLogo';

const GITHUB_PROJECT_URL = 'https://github.com/mumu-0922/GankAIGC';

const featureCards = [
  {
    title: '智能降 AI',
    desc: '针对论文文本做句式重构与表达润色，减少机械化、模板化表达。',
    icon: Sparkles,
    tone: 'bg-[#E1F3FE] text-[#1F6C9F]',
  },
  {
    title: '语义保持',
    desc: '先守住原意和论证结构，再处理高风险句，避免越改越偏。',
    icon: FileText,
    tone: 'bg-[#EDF3EC] text-[#346538]',
  },
  {
    title: '账号体系',
    desc: '注册登录后按啤酒使用，支持兑换码充值啤酒与自带 API。',
    icon: KeyRound,
    tone: 'bg-[#FBF3DB] text-[#956400]',
  },
];

const problemCards = [
  {
    title: 'AI 痕迹集中在句式',
    desc: '重复转折、过度平滑、空泛连接词，往往比单个词更容易暴露机器感。',
  },
  {
    title: '粗暴改写会伤原意',
    desc: '论文不是营销文，降 AI 的第一原则是保留论点、术语和段落逻辑。',
  },
  {
    title: '处理记录需要可复核',
    desc: '从初稿到投稿前，每次处理都应该能回看，避免最终版本失控。',
  },
];

const workflowSteps = [
  {
    step: '阶段 01',
    title: '初稿降 AI',
    desc: '先处理明显机器感表达，压低高风险句式，同时保留论文原有结构。',
  },
  {
    step: '阶段 02',
    title: '二稿优化',
    desc: '对语序、衔接和学术表达做细调，让文字更接近人工写作习惯。',
  },
  {
    step: '阶段 03',
    title: '投稿前检查',
    desc: '归档处理结果和关键改动，方便你复查每一次优化后的文本。',
  },
];

const WelcomePage = () => {
  const navigate = useNavigate();

  const goTo = (path) => {
    navigate(path);
  };

  return (
    <div className="min-h-screen overflow-x-hidden bg-[#FBFBFA] text-[#111111]">
      <a
        href="#home"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-[#111111] focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white"
      >
        跳到主要内容
      </a>

      <header className="fixed inset-x-0 top-0 z-50 border-b border-[#EAEAEA]/90 bg-[#FBFBFA]/92 backdrop-blur-xl">
        <nav className="mx-auto flex min-h-[72px] max-w-6xl items-center justify-between px-5 sm:px-8" aria-label="首页导航">
          <BrandLogo size="sm" />

          <div className="hidden items-center gap-7 text-sm font-medium text-[#6B7280] md:flex">
            <a className="transition hover:text-[#111111]" href="#features">能力</a>
            <a className="transition hover:text-[#111111]" href="#scenarios">链路</a>
            <a className="transition hover:text-[#111111]" href="#security">可信</a>
          </div>

          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={() => goTo('/admin')}
              className="hidden items-center gap-2 rounded-md border border-[#EAEAEA] bg-white px-3.5 py-2 text-sm font-semibold text-[#2F3437] transition hover:border-[#D8D8D8] hover:bg-[#F7F6F3] active:scale-[0.98] sm:flex"
            >
              <Shield className="h-4 w-4 text-[#185FA5]" />
              管理后台
            </button>
            <button
              type="button"
              onClick={() => goTo('/login')}
              className="inline-flex items-center gap-2 rounded-md bg-[#111111] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#333333] active:scale-[0.98]"
            >
              <LogIn className="h-4 w-4" />
              登录 / 注册
            </button>
          </div>
        </nav>
      </header>

      <main id="home" className="relative pt-[72px]">
        <section className="mx-auto max-w-5xl px-5 pb-20 pt-20 text-center sm:px-8 sm:pb-24 sm:pt-24">
          <div className="mx-auto mb-7 inline-flex items-center gap-2 rounded-full bg-[#E6F1FB] px-4 py-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-[#185FA5]">
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            论文降 AI 与语义润色工具
          </div>

          <h1 className="text-balance text-[44px] font-semibold tracking-[-0.045em] text-[#111111] sm:text-[64px] sm:leading-[1.02]">
            让论文原创更简单
          </h1>

          <p className="mx-auto mt-6 max-w-3xl text-balance text-2xl font-medium tracking-[-0.02em] text-[#2F3437] sm:text-3xl">
            把 AI 痕迹压下去，把论文原意留下来
          </p>

          <p className="mx-auto mt-6 max-w-2xl text-base leading-8 text-[#6B7280] sm:text-lg">
            GankAIGC 聚焦论文降 AI、学术润色与原创性增强，支持账号登录、邀请码注册、兑换码充值啤酒和自带 API 使用。
          </p>

          <div className="mt-9 flex flex-col justify-center gap-3 sm:flex-row">
            <button
              type="button"
              onClick={() => goTo('/login')}
              className="inline-flex min-h-[48px] items-center justify-center gap-2 rounded-md bg-[#111111] px-7 text-sm font-semibold text-white transition hover:bg-[#333333] active:scale-[0.98]"
            >
              开始使用
              <ArrowRight className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => goTo('/register')}
              className="inline-flex min-h-[48px] items-center justify-center gap-2 rounded-md border border-[#EAEAEA] bg-white px-7 text-sm font-semibold text-[#111111] transition hover:border-[#D8D8D8] hover:bg-[#F7F6F3] active:scale-[0.98]"
            >
              <UserPlus className="h-4 w-4 text-[#185FA5]" />
              邀请码注册
            </button>
          </div>

          <div id="security" className="mx-auto mt-8 flex scroll-mt-24 max-w-3xl flex-wrap justify-center gap-x-5 gap-y-2 text-sm text-[#6B7280]">
            {['语义保持', '账号隔离', '按啤酒使用', '啤酒与自带 API 双模式'].map((item) => (
              <span key={item} className="inline-flex items-center gap-1.5">
                <CheckCircle className="h-4 w-4 text-[#346538]" aria-hidden="true" />
                {item}
              </span>
            ))}
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-5 pb-20 sm:px-8">
          <div className="grid overflow-hidden rounded-xl border border-[#EAEAEA] bg-white md:grid-cols-[0.9fr_1.1fr]">
            <div className="border-b border-[#EAEAEA] p-6 text-left md:border-b-0 md:border-r md:p-8">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#185FA5]">检测报告缩影</p>
              <h2 className="mt-4 max-w-md text-3xl font-semibold tracking-[-0.035em] text-[#111111]">
                不追求花哨，只把风险句和改写结果摆清楚。
              </h2>
              <p className="mt-5 max-w-md text-sm leading-7 text-[#6B7280]">
                首页保留优化前、优化后和 AI 率检测结果，但把它们收进一个更像文档报告的低噪声面板。
              </p>
            </div>

            <div className="grid gap-4 bg-[#F7F6F3] p-5 sm:grid-cols-2 sm:p-6">
              <article className="rounded-xl border border-[#EAEAEA] bg-white p-5">
                <div className="mb-5 flex items-center justify-between gap-3">
                  <span className="rounded-full bg-[#FDEBEC] px-3 py-1 text-xs font-semibold text-[#9F2F2D]">优化前</span>
                  <AlertTriangle className="h-4 w-4 text-[#9F2F2D]" aria-hidden="true" />
                </div>
                <div className="space-y-2.5" aria-hidden="true">
                  <div className="h-2.5 rounded-full bg-[#E5E7EB]" />
                  <div className="h-2.5 w-10/12 rounded-full bg-[#F9C7CA]" />
                  <div className="h-2.5 w-11/12 rounded-full bg-[#E5E7EB]" />
                  <div className="h-2.5 w-8/12 rounded-full bg-[#F9C7CA]" />
                </div>
                <div className="mt-6 border-t border-[#EAEAEA] pt-4">
                  <p className="text-xs font-medium text-[#787774]">AI 率检测结果</p>
                  <p className="mt-1 font-mono text-4xl font-semibold tracking-[-0.04em] text-[#9F2F2D]">99%</p>
                </div>
              </article>

              <article className="rounded-xl border border-[#EAEAEA] bg-white p-5">
                <div className="mb-5 flex items-center justify-between gap-3">
                  <span className="rounded-full bg-[#E1F3FE] px-3 py-1 text-xs font-semibold text-[#1F6C9F]">优化后</span>
                  <ShieldCheck className="h-4 w-4 text-[#1F6C9F]" aria-hidden="true" />
                </div>
                <div className="space-y-2.5" aria-hidden="true">
                  <div className="h-2.5 rounded-full bg-[#E5E7EB]" />
                  <div className="h-2.5 w-10/12 rounded-full bg-[#BFE4FA]" />
                  <div className="h-2.5 w-11/12 rounded-full bg-[#E5E7EB]" />
                  <div className="h-2.5 w-8/12 rounded-full bg-[#BFE4FA]" />
                </div>
                <div className="mt-6 border-t border-[#EAEAEA] pt-4">
                  <p className="text-xs font-medium text-[#787774]">AI 率检测结果</p>
                  <p className="mt-1 font-mono text-4xl font-semibold tracking-[-0.04em] text-[#1F6C9F]">0%</p>
                </div>
              </article>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-5 py-20 sm:px-8" aria-labelledby="problem-title">
          <div className="max-w-2xl text-left">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#185FA5]">问题先看清</p>
            <h2 id="problem-title" className="mt-3 text-3xl font-semibold tracking-[-0.035em] text-[#111111] sm:text-4xl">
              论文降 AI，不是把句子随便换一种说法。
            </h2>
            <p className="mt-4 text-base leading-8 text-[#6B7280]">
              真正要处理的是机器感、段落节奏和学术表达稳定性，而不是堆砌同义词。
            </p>
          </div>

          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {problemCards.map(({ title, desc }) => (
              <article key={title} className="rounded-xl border border-[#EAEAEA] bg-white p-6 transition hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(0,0,0,0.04)]">
                <h3 className="text-base font-semibold text-[#111111]">{title}</h3>
                <p className="mt-3 text-sm leading-7 text-[#6B7280]">{desc}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="features" className="mx-auto max-w-6xl scroll-mt-24 px-5 py-20 sm:px-8" aria-labelledby="feature-title">
          <div className="grid gap-10 lg:grid-cols-[0.78fr_1.22fr] lg:items-start">
            <div className="text-left">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#185FA5]">核心能力</p>
              <h2 id="feature-title" className="mt-3 text-3xl font-semibold tracking-[-0.035em] text-[#111111] sm:text-4xl">
                少一点包装，多一点可用。
              </h2>
              <p className="mt-4 text-base leading-8 text-[#6B7280]">
                保留你当前产品真实能力，不写虚假的论文格式、检测准确率或机构背书。
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-1">
              {featureCards.map(({ title, desc, icon: Icon, tone }) => (
                <article key={title} className="grid gap-5 rounded-xl border border-[#EAEAEA] bg-white p-6 sm:block lg:grid lg:grid-cols-[auto_1fr] lg:items-start">
                  <div className={`mb-4 grid h-11 w-11 place-items-center rounded-lg ${tone} lg:mb-0`}>
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div>
                    <h3 className="text-base font-semibold text-[#111111]">{title}</h3>
                    <p className="mt-2 text-sm leading-7 text-[#6B7280]">{desc}</p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="scenarios" data-home-scenarios="workflow" className="mx-auto max-w-6xl scroll-mt-24 px-5 py-20 sm:px-8" aria-labelledby="workflow-title">
          <div className="rounded-xl border border-[#EAEAEA] bg-white p-6 sm:p-8">
            <div className="mb-8 max-w-2xl">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#185FA5]">论文处理链路</p>
              <h2 id="workflow-title" className="mt-3 text-3xl font-semibold tracking-[-0.035em] text-[#111111] sm:text-4xl">
                从初稿到投稿前的三步优化
              </h2>
              <p className="mt-4 text-base leading-8 text-[#6B7280]">
                流程压缩成三段：先降风险，再稳语义，最后复核处理记录。
              </p>
            </div>

            <div className="divide-y divide-[#EAEAEA]">
              {workflowSteps.map(({ step, title, desc }) => (
                <article key={step} className="grid gap-4 py-6 first:pt-0 last:pb-0 sm:grid-cols-[9rem_1fr] sm:items-start">
                  <div className="font-mono text-xs font-semibold uppercase tracking-[0.12em] text-[#185FA5]">{step}</div>
                  <div>
                    <h3 className="text-lg font-semibold tracking-[-0.02em] text-[#111111]">{title}</h3>
                    <p className="mt-2 max-w-2xl text-sm leading-7 text-[#6B7280]">{desc}</p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section data-home-github-star="footer" className="mx-auto max-w-6xl px-5 py-20 sm:px-8">
          <div className="flex flex-col gap-6 rounded-xl border border-[#EAEAEA] bg-white p-6 text-[#111111] sm:flex-row sm:items-center sm:justify-between sm:p-8">
            <div className="flex items-start gap-4">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-[#F7F6F3] text-[#2F3437]">
                <Github className="h-5 w-5" aria-hidden="true" />
              </div>
              <div>
                <p className="text-lg font-semibold">GitHub 项目</p>
                <p className="mt-2 max-w-xl text-sm leading-7 text-[#6B7280]">
                  项目持续迭代中，觉得有用欢迎点个 Star。反馈越具体，下一刀越准。
                </p>
              </div>
            </div>

            <a
              href={GITHUB_PROJECT_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-md border border-[#EAEAEA] bg-[#FBFBFA] px-5 text-sm font-semibold text-[#111111] transition hover:border-[#D8D8D8] hover:bg-[#F7F6F3] active:scale-[0.98]"
              aria-label="打开项目仓库，求 Star"
            >
              <Star className="h-4 w-4 fill-[#F4C430] text-[#F4C430]" aria-hidden="true" />
              求 Star
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </a>
          </div>
        </section>
      </main>
    </div>
  );
};

export default WelcomePage;

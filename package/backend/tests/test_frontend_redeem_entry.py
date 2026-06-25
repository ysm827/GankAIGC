from pathlib import Path
import re


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PACKAGE_ROOT / "frontend"
FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
STATIC_DIR = PACKAGE_ROOT / "static"


def _read_static_js_assets():
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((STATIC_DIR / "assets").glob("*.js"))
    )


def test_user_menu_exposes_explicit_redeem_entry():
    user_menu = (FRONTEND_SRC / "components" / "UserMenu.jsx").read_text(encoding="utf-8")
    beer_icon = (FRONTEND_SRC / "components" / "BeerIcon.jsx").read_text(encoding="utf-8")
    beer_asset = (FRONTEND_SRC / "assets" / "beer-mug-twemoji.svg").read_text(encoding="utf-8")

    assert "兑换啤酒" in user_menu
    assert "BeerIcon" in user_menu
    assert '<BeerIcon className="w-4 h-4" />' in user_menu
    assert '<KeyRound className="w-4 h-4 text-amber-500" />' in user_menu
    assert user_menu.count('to="/credits"') == 1
    assert "beer-mug-twemoji.svg" in beer_icon
    assert 'viewBox="0 0 36 36"' in beer_asset
    assert "#FFCC4D" in beer_asset


def test_credit_transactions_render_backend_utc_as_china_time():
    date_utils = (FRONTEND_SRC / "utils" / "dateTime.js").read_text(encoding="utf-8")
    credits_page = (FRONTEND_SRC / "pages" / "CreditsPage.jsx").read_text(encoding="utf-8")

    assert "Asia/Shanghai" in date_utils
    assert "endsWith('Z')" in date_utils
    assert "formatChinaDateTime" in credits_page
    assert "formatChinaDateTime(transaction.created_at)" in credits_page
    assert "new Date(transaction.created_at).toLocaleString()" not in credits_page


def test_credit_transaction_pages_show_labeled_beer_flow():
    api = (FRONTEND_SRC / "api" / "index.js").read_text(encoding="utf-8")
    credits_page = (FRONTEND_SRC / "pages" / "CreditsPage.jsx").read_text(encoding="utf-8")
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")

    assert "listCreditTransactions: (limit = 50)" in api
    assert "reason_label" in credits_page
    assert "balance_after" in credits_page
    assert "related_session_title" in credits_page
    assert "最近啤酒流水" in admin_dashboard
    assert "/api/admin/credit-transactions" in admin_dashboard
    assert "reason_label" in admin_dashboard
    assert "balance_after" in admin_dashboard


def test_served_static_bundle_includes_china_time_formatter():
    static_bundle = _read_static_js_assets()

    assert "Asia/Shanghai" in static_bundle
    assert "hour12" in static_bundle


def test_frontend_uses_brand_logo_as_favicon():
    frontend_index = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    static_index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    brand_logo = (FRONTEND_SRC / "components" / "BrandLogo.jsx").read_text(encoding="utf-8")

    for index_html in (frontend_index, static_index):
        assert 'rel="icon"' in index_html
        assert 'type="image/svg+xml"' in index_html
        assert 'href="/gankaigc-logo.svg"' in index_html
        assert "/shiliang.svg" not in index_html
        assert "/vite.svg" not in index_html

    for logo_path in (FRONTEND_ROOT / "public" / "gankaigc-logo.svg", STATIC_DIR / "gankaigc-logo.svg"):
        logo_svg = logo_path.read_text(encoding="utf-8")

        assert 'viewBox="442 369 1180 1180"' in logo_svg
        assert 'preserveAspectRatio="xMidYMid meet"' in logo_svg
        assert 'viewBox="0 0 2048 2048"' not in logo_svg
        assert 'preserveAspectRatio="none"' not in logo_svg

    assert not (FRONTEND_ROOT / "public" / "shiliang.svg").exists()
    assert not (STATIC_DIR / "shiliang.svg").exists()
    assert not (FRONTEND_ROOT / "public" / "gankaigc-logo.png").exists()
    assert not (STATIC_DIR / "gankaigc-logo.png").exists()
    assert 'src="/gankaigc-logo.svg"' in brand_logo
    assert "/shiliang.svg" not in brand_logo
    assert "/gankaigc-logo.png" not in brand_logo


def test_welcome_page_focuses_on_ai_reduction_not_word_formatting():
    welcome_page = (FRONTEND_SRC / "pages" / "WelcomePage.jsx").read_text(encoding="utf-8")

    assert "让论文原创更简单" in welcome_page
    assert "开始使用" in welcome_page
    assert "登录 / 注册" in welcome_page
    assert "优化前" in welcome_page
    assert "优化后" in welcome_page
    assert "AI 率检测结果" in welcome_page
    assert 'data-home-scenarios="workflow"' in welcome_page
    assert "论文处理链路" in welcome_page
    assert "阶段 01" in welcome_page
    assert "从初稿到投稿前的三步优化" in welcome_page
    assert "阶段 04" not in welcome_page
    assert "有自有模型额度时，可切换为自带 API 模式" not in welcome_page
    assert "账号次数与自带 API 双模式" not in welcome_page
    assert "论文原创性工作台" not in welcome_page
    assert "功能介绍" not in welcome_page
    assert "使用场景" not in welcome_page
    assert "安全保障" not in welcome_page
    assert "Word 排版" not in welcome_page


def test_welcome_page_links_to_github_project_and_requests_star():
    welcome_page = (FRONTEND_SRC / "pages" / "WelcomePage.jsx").read_text(encoding="utf-8")

    assert "https://github.com/mumu-0922/GankAIGC" in welcome_page
    assert "GitHub 项目" in welcome_page
    assert "求 Star" in welcome_page
    assert 'data-home-github-star="footer"' in welcome_page
    assert welcome_page.count("GitHub 项目") == 1
    assert welcome_page.index('data-home-scenarios="workflow"') < welcome_page.index("GitHub 项目")
    assert 'target="_blank"' in welcome_page
    assert 'rel="noopener noreferrer"' in welcome_page


def test_workspace_queue_status_uses_processing_task_label():
    workspace = (FRONTEND_SRC / "pages" / "WorkspacePage.jsx").read_text(encoding="utf-8")

    assert "ListChecks" in workspace
    assert "在线 {queueStatus.online_users ?? 0}" in workspace
    assert "bg-emerald-500" in workspace
    assert "WORKSPACE_QUEUE_POLL_INTERVAL_MS = 15000" in workspace
    assert "ACTIVE_SESSION_POLL_INTERVAL_MS = 6000" in workspace
    assert "document.visibilityState !== 'visible'" in workspace
    assert "处理中 {queueStatus.current_users}/{queueStatus.max_users}" in workspace
    assert "Users className" not in workspace


def test_workspace_project_archive_and_history_controls_are_actionable():
    workspace = (FRONTEND_SRC / "pages" / "WorkspacePage.jsx").read_text(encoding="utf-8")
    api = (FRONTEND_SRC / "api" / "index.js").read_text(encoding="utf-8")
    optimization_routes = (PACKAGE_ROOT / "backend" / "app" / "routes" / "optimization.py").read_text(encoding="utf-8")
    schemas = (PACKAGE_ROOT / "backend" / "app" / "schemas.py").read_text(encoding="utf-8")
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")

    assert "const HISTORY_STATUS_FILTERS" in workspace
    assert "{ id: 'completed', label: '已完成' }" in workspace
    assert "{ id: 'failed', label: '失败' }" in workspace
    assert "const [historyStatusFilter, setHistoryStatusFilter] = useState('all')" in workspace
    assert "const [showHistoryFilters, setShowHistoryFilters] = useState(false)" in workspace
    assert "const filteredSessions = useMemo" in workspace
    assert "sessions.filter((session) => session.status === historyStatusFilter)" in workspace
    assert "aria-label=\"筛选历史状态\"" in workspace
    assert "aria-expanded={showHistoryFilters}" in workspace
    assert "HISTORY_STATUS_FILTERS.map((filter)" in workspace
    assert "handleHistoryStatusFilterChange('all')" in workspace

    assert "const projectSelectValue = activeProjectId === null ? 'all'" in workspace
    assert '<option value="all">全部历史</option>' in workspace
    assert '<option value="0">未归档历史</option>' in workspace
    assert "全部项目" not in workspace
    assert "handleProjectScopeChange" in workspace
    assert "value === 'all' ? null : Number(value)" in workspace
    assert "setActiveProjectId(null)" in workspace
    assert "await loadSessions(null)" in workspace
    assert "handleViewAllHistory" not in workspace
    assert "刷新全部历史" not in workspace
    assert "查看全部历史" not in workspace
    assert "aurora-history-more" not in workspace

    assert "归入项目" in workspace
    assert "handleMoveSessionToProject" in workspace
    assert "optimizationAPI.updateSessionProject(session.session_id" in workspace
    assert "project_id: projectId" in workspace
    assert "shouldRemoveFromCurrentScope" in workspace
    assert "FolderInput" in workspace
    assert "openProjectMenuSessionId" in workspace
    assert "handleToggleProjectMenu" in workspace
    assert "aurora-session-project-trigger" in workspace
    assert "aurora-session-project-menu" in workspace
    assert 'role="menu"' in workspace
    assert 'role="menuitem"' in workspace
    assert "选择目标项目" in workspace
    assert "aurora-session-project-select" not in workspace
    assert "归档当前项目" in workspace
    assert "编辑当前项目" in workspace
    assert "选择具体项目后可编辑或隐藏项目" in workspace
    assert "未归档记录可在卡片上点“归入项目”" in workspace
    assert "projectAPI.archive(project.id)" in workspace

    assert "updateSessionProject: (sessionId, data)" in api
    assert "api.patch(`/optimization/sessions/${sessionId}/project`, data" in api
    assert "SessionProjectUpdateRequest" in schemas
    assert '@router.patch("/sessions/{session_id}/project", response_model=SessionResponse)' in optimization_routes
    assert "session.project_id = project.id if project else None" in optimization_routes
    assert "PaperProject.is_archived.is_(False)" in optimization_routes

    assert ".aurora-history-head" in index_css
    assert "z-index: 80" in index_css
    assert ".aurora-history-filter-menu" in index_css
    assert "z-index: 120" in index_css
    assert ".aurora-session-project-move" in index_css
    assert ".aurora-session-project-trigger" in index_css
    assert ".aurora-session-project-menu" in index_css
    assert ".aurora-session-project-option" in index_css
    assert ".aurora-session-project-select" not in index_css


def test_workspace_persists_selected_processing_and_billing_modes():
    workspace = (FRONTEND_SRC / "pages" / "WorkspacePage.jsx").read_text(encoding="utf-8")

    assert "gankaigc.workspace.processingMode" in workspace
    assert "gankaigc.workspace.billingMode" in workspace
    assert "DEFAULT_PROCESSING_MODE = 'paper_polish'" in workspace
    assert "DEFAULT_BILLING_MODE = 'platform'" in workspace
    assert "getInitialProcessingMode" in workspace
    assert "getInitialBillingMode" in workspace
    assert "localStorage.getItem(WORKSPACE_PROCESSING_MODE_STORAGE_KEY)" in workspace
    assert "localStorage.getItem(WORKSPACE_BILLING_MODE_STORAGE_KEY)" in workspace
    assert "localStorage.setItem(WORKSPACE_PROCESSING_MODE_STORAGE_KEY, processingMode)" in workspace
    assert "localStorage.setItem(WORKSPACE_BILLING_MODE_STORAGE_KEY, billingMode)" in workspace
    assert "PROCESSING_MODE_IDS.has(savedMode)" in workspace
    assert "BILLING_MODE_IDS.has(savedMode)" in workspace
    assert "PROCESSING_MODE_IDS.has(nextMode)" in workspace
    assert "useState(getInitialProcessingMode)" in workspace
    assert "useState(getInitialBillingMode)" in workspace
    assert "onChange={handleProcessingModeChange}" in workspace
    assert "gank-segmented-control aurora-mode-list aurora-billing-list" in workspace
    assert "aurora-mode-card aurora-billing-card" in workspace
    assert "aurora-check-dot" not in workspace
    assert "aurora-radio-dot" not in workspace


def test_workspace_zhuque_status_polling_avoids_overlapping_requests():
    workspace = (FRONTEND_SRC / "pages" / "WorkspacePage.jsx").read_text(encoding="utf-8")

    assert "ZHUQUE_STATUS_POLL_INTERVAL_MS = 1000" in workspace
    assert "ZHUQUE_STATUS_FAST_POLL_INTERVAL_MS = 350" in workspace
    assert "ZHUQUE_STATUS_FAST_POLL_DURATION_MS = 12000" in workspace
    assert "isLoadingZhuqueStatusRef = useRef(false)" in workspace
    assert "loadZhuqueStatusPanel" in workspace
    assert "if (isLoadingZhuqueStatusRef.current)" in workspace
    assert "Promise.all([" in workspace
    assert "document.visibilityState !== 'visible'" in workspace
    assert "loadZhuqueAuthStatus();" not in workspace
    assert "loadZhuqueReadiness();" not in workspace


def test_frontend_routes_are_lazy_loaded_and_sse_updates_are_throttled():
    app = (FRONTEND_SRC / "App.jsx").read_text(encoding="utf-8")
    session_detail = (FRONTEND_SRC / "pages" / "SessionDetailPage.jsx").read_text(encoding="utf-8")

    assert "lazy(() => import('./pages/WorkspacePage'))" in app
    assert "lazy(() => import('./pages/SessionDetailPage'))" in app
    assert "Suspense fallback={<RouteFallback />}" in app
    assert "import WorkspacePage from './pages/WorkspacePage'" not in app
    assert "import SessionDetailPage from './pages/SessionDetailPage'" not in app

    assert "STREAM_FLUSH_INTERVAL_MS = 100" in session_detail
    assert "pendingContentUpdatesRef" in session_detail
    assert "pendingZhuqueEventsRef" in session_detail
    assert "streamFlushTimerRef" in session_detail
    assert "enqueueStreamUpdate({ kind: 'content', data })" in session_detail
    assert "window.setTimeout" in session_detail
    assert "window.clearTimeout(streamFlushTimerRef.current)" in session_detail


def test_session_detail_does_not_render_failed_zhuque_detection_as_zero_percent():
    session_detail = (FRONTEND_SRC / "pages" / "SessionDetailPage.jsx").read_text(encoding="utf-8")
    static_bundle = _read_static_js_assets()

    assert "result?.success === false" in session_detail
    assert "zhuqueReport.isInvalid" in session_detail
    assert "formatRemainingUses" in session_detail
    assert "number < 0" in session_detail
    assert "检测无效" in session_detail
    assert "暂无有效占比" in session_detail

    assert "检测无效" in static_bundle
    assert "暂无有效占比" in static_bundle


def test_frontend_uses_apple_glass_theme_tokens():
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")
    workspace = (FRONTEND_SRC / "pages" / "WorkspacePage.jsx").read_text(encoding="utf-8")
    session_detail = (FRONTEND_SRC / "pages" / "SessionDetailPage.jsx").read_text(encoding="utf-8")
    static_index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    css_bundle_match = re.search(r'href="/assets/(index-[^"]+\.css)"', static_index)
    assert css_bundle_match
    static_css_bundle = (STATIC_DIR / "assets" / css_bundle_match.group(1)).read_text(encoding="utf-8")

    for css in (index_css, static_css_bundle):
        assert "--glass-bg:" in css
        assert "--glass-bg-strong:" in css
        assert "--glass-blur:" in css
        assert "--glass-edge:" in css
        assert "--glass-refraction:" in css
        assert "--glass-radius-xl:" in css
        assert "--app-accent:" in css
        assert "--apple-blue:" in css
        assert "--apple-ink:" in css
        assert "--apple-parchment:" in css
        assert "--apple-dark-tile:" in css
        assert "gank-ambient-orb" in css
        assert "gank-liquid-panel" in css
        assert "apple-product-tile" in css
        assert "apple-product-tile-dark" in css
        assert "apple-action-pill" in css
        assert "apple-subnav" in css
        assert "gank-glass-choice-active" in css
        assert "prefers-reduced-transparency" in css
        assert "@supports not ((backdrop-filter" in css
        assert "color-scheme:" in css and "light" in css

    assert "AI PAPER RECONSTRUCTION" in workspace
    assert "apple-product-tile" in workspace
    assert "apple-paper-stage" in workspace
    assert "apple-action-pill" in workspace
    assert "apple-subnav" in workspace
    assert "朱雀检测" in workspace
    assert "论文重构" in workspace
    assert "全文复检" in workspace
    assert "gank-liquid-panel" in workspace
    assert "gank-segmented-control" in workspace
    assert "gank-glass-status-grid" in workspace
    assert "gank-glass-choice-active" in workspace
    assert "gank-glass-choice-warm" not in workspace
    assert "aurora-billing-list" in workspace
    assert "aurora-mode-card aurora-billing-card" in workspace
    assert "gank-ambient-orb orb-one" in workspace

    assert "gank-liquid-panel" in session_detail
    assert "ArrowLeft" in session_detail
    assert "aurora-detail-back-link" in session_detail
    assert "apple-report-stage" in session_detail
    assert "apple-utility-card" in session_detail
    assert "检测报告预览" in session_detail
    assert "gank-agent-scroll" in session_detail
    assert "gank-text-panel" in session_detail
    assert "gank-segmented-control" in session_detail
    assert "gank-ambient-orb orb-two" in session_detail


def test_account_credit_and_api_pages_use_aurora_theme_shell():
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")
    profile_page = (FRONTEND_SRC / "pages" / "ProfilePage.jsx").read_text(encoding="utf-8")
    credits_page = (FRONTEND_SRC / "pages" / "CreditsPage.jsx").read_text(encoding="utf-8")
    api_settings_page = (FRONTEND_SRC / "pages" / "ApiSettingsPage.jsx").read_text(encoding="utf-8")
    static_bundle = _read_static_js_assets()

    decorative_english_labels = [
        "ACCOUNT CONTROL",
        "DISPLAY NAME",
        "SECURITY",
        "INVITE CODE",
        "BEER BALANCE",
        "CURRENT BALANCE",
        "TRANSACTION LEDGER",
        "MODEL PROVIDER",
        "PRIVATE PROVIDER",
        "CONFIGURATION",
    ]

    for page in (profile_page, credits_page, api_settings_page):
        assert "gank-app-page aurora-app-page aurora-account-page" in page
        assert "apple-global-nav aurora-topbar" in page
        assert "aurora-brand-logo" in page
        assert "aurora-account-back-link" in page
        assert "返回工作台" in page
        assert "aurora-page-shell aurora-account-shell" in page
        assert "aurora-account-hero-blank" not in page
        assert "apple-utility-card aurora-account-card" in page
        assert "aurora-input" in page
        for label in decorative_english_labels:
            assert label not in page

    assert "保存昵称" in profile_page
    assert "保存密码" in profile_page
    assert "我的邀请码" in profile_page
    assert "gank-glass-toolbar" not in profile_page

    assert "平台啤酒" in credits_page
    assert "啤酒流水" in credits_page
    assert "aurora-ledger-list custom-scrollbar" in credits_page
    assert "aurora-credit-balance-unlimited" in credits_page
    assert "gank-glass-card" not in credits_page

    assert "自带 API 配置" in api_settings_page
    assert "供应商配置" in api_settings_page
    assert "aurora-saved-key-notice" in api_settings_page
    assert "gank-card rounded-[2rem]" not in api_settings_page

    assert ".aurora-account-page" in index_css
    assert ".aurora-account-hero" in index_css
    assert ".aurora-account-hero-blank" not in index_css
    assert ".aurora-account-card.apple-utility-card" in index_css
    assert ".aurora-account-primary.apple-action-pill" in index_css
    assert ".aurora-ledger-item" in index_css
    assert ".aurora-api-form" in index_css

    assert "aurora-account-page" in static_bundle
    assert "aurora-account-hero-blank" not in static_bundle
    assert "aurora-credit-balance-unlimited" in static_bundle
    for label in decorative_english_labels:
        assert label not in static_bundle


def test_frontend_glass_theme_has_runtime_performance_guardrails():
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")
    static_index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    css_bundle_match = re.search(r'href="/assets/(index-[^"]+\.css)"', static_index)
    assert css_bundle_match
    static_css_bundle = (STATIC_DIR / "assets" / css_bundle_match.group(1)).read_text(encoding="utf-8")

    assert "Runtime performance guardrail" in index_css
    for css in (index_css, static_css_bundle):
        compact_css = css.replace(" ", "")
        assert ".gank-liquid-panel," in css
        assert ".apple-global-nav," in css
        assert ".aurora-session-topbar," in css
        assert "backdrop-filter:none!important" in compact_css
        assert "-webkit-backdrop-filter:none!important" in compact_css
        assert ".gank-ambient-orb," in css
        assert "content-visibility:auto" in compact_css
        assert "contain:layoutpaintstyle" in compact_css
        assert "filter:none!important" in compact_css
        assert "will-change:auto" in compact_css
        assert "display:none!important" in compact_css


def test_workspace_retry_uses_internal_dialog_and_current_billing_mode():
    workspace = (FRONTEND_SRC / "pages" / "WorkspacePage.jsx").read_text(encoding="utf-8")
    api = (FRONTEND_SRC / "api" / "index.js").read_text(encoding="utf-8")

    assert "retryDialogSession" in workspace
    assert "confirmRetrySegment" in workspace
    assert "继续处理失败任务？" in workspace
    assert "window.confirm('检测到会话执行失败" not in workspace
    assert "billing_mode: billingMode" in workspace
    assert "请先保存自带 API 配置" in workspace
    assert "navigate('/api-settings')" in workspace
    assert "retryFailedSegments: (sessionId, data = {})" in api
    assert "api.post(`/optimization/sessions/${sessionId}/retry`, data" in api


def test_user_menu_hides_word_formatter_entry_until_feature_is_ready():
    user_menu = (FRONTEND_SRC / "components" / "UserMenu.jsx").read_text(encoding="utf-8")

    assert "Word 排版" not in user_menu
    assert 'to="/word-formatter"' not in user_menu


def test_admin_dashboard_hides_legacy_card_key_management():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")

    assert "操作日志" in admin_dashboard
    assert "/api/admin/audit-logs" in admin_dashboard
    assert "auditLogs" in admin_dashboard
    assert "啤酒兑换码" in admin_dashboard
    assert "用户列表" in admin_dashboard
    assert "平台啤酒" in admin_dashboard
    assert "设为无限" in admin_dashboard
    assert "取消无限" in admin_dashboard
    assert "邀请码管理" in admin_dashboard
    assert "邀请码、兑换码和用户余额统一在这里管理。" not in admin_dashboard
    assert "前往管理" not in admin_dashboard
    assert "生成卡密" not in admin_dashboard
    assert "/api/admin/credit-codes/batch" in admin_dashboard
    assert "批量生成" in admin_dashboard
    assert "使用次数" not in admin_dashboard
    assert "账号次数" not in admin_dashboard
    assert "额度兑换码" not in admin_dashboard
    assert "用户额度余额" not in admin_dashboard
    assert "无限调用" not in admin_dashboard
    assert "/api/admin/card-keys" not in admin_dashboard
    assert "/api/admin/batch-generate-keys" not in admin_dashboard
    assert "/api/admin/users/${userId}/usage" not in admin_dashboard


def test_admin_invite_and_credit_code_forms_use_matching_layout():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")

    assert "ADMIN_ACCOUNT_FORM_CLASS" in admin_dashboard
    assert "ADMIN_ACCOUNT_INPUT_CLASS" in admin_dashboard
    assert "ADMIN_ACCOUNT_WIDE_INPUT_CLASS" in admin_dashboard
    assert "ADMIN_ACCOUNT_ACTION_BUTTON_CLASS" in admin_dashboard
    assert admin_dashboard.count("className={ADMIN_ACCOUNT_FORM_CLASS}") == 2
    assert admin_dashboard.count("className={ADMIN_ACCOUNT_WIDE_INPUT_CLASS}") == 1
    assert admin_dashboard.count("className={ADMIN_ACCOUNT_INPUT_CLASS}") >= 2
    assert admin_dashboard.count("className={ADMIN_ACCOUNT_ACTION_BUTTON_CLASS}") == 2
    assert "sm:grid-cols-[minmax(0,1fr)_5rem_7rem]" in admin_dashboard
    assert 'placeholder="兑换码，可留空生成"' in admin_dashboard
    assert "sm:col-span-2" in admin_dashboard
    assert "min-w-[7rem]" in admin_dashboard
    assert 'aria-hidden="true"' not in admin_dashboard
    assert "grid grid-cols-1 sm:grid-cols-[1fr_120px_auto]" not in admin_dashboard


def test_admin_update_modal_uses_source_and_release_latest_state():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")

    assert "DownloadCloud" in admin_dashboard
    assert "window.__GANKAIGC_RUNTIME__?.appVersion" in admin_dashboard
    assert "if (isAuthenticated && !updateStatus)" in admin_dashboard
    assert "fetchUpdateStatus({ silent: true })" in admin_dashboard
    assert "toast.error(error.response?.data?.detail || '检查更新失败')" in admin_dashboard
    assert "const updateAvailable" in admin_dashboard
    assert "const updateStatusLabel" in admin_dashboard
    assert "已是最新版本" in admin_dashboard
    assert "复制 SSH 升级命令" in admin_dashboard
    assert "git fetch --tags origin main" in admin_dashboard
    assert "git pull --ff-only origin main" in admin_dashboard
    assert "docker compose --env-file .env.docker up -d --build" in admin_dashboard
    assert "源码状态" not in admin_dashboard
    assert "/app/source" not in admin_dashboard
    assert "为降低风险" not in admin_dashboard
    assert "后台不直接控制 Docker" not in admin_dashboard
    assert "VPS 在线更新" not in admin_dashboard
    assert "确认开始 VPS 在线更新" not in admin_dashboard
    assert "handleRunVpsUpdate" not in admin_dashboard
    assert "can_run_update && updateAvailable" not in admin_dashboard


def test_spa_index_injects_runtime_version_before_react_bootstrap():
    main_entry = (PACKAGE_ROOT / "main.py").read_text(encoding="utf-8")
    backend_main = (FRONTEND_SRC.parents[1] / "backend" / "app" / "main.py").read_text(encoding="utf-8")

    for content in (main_entry, backend_main):
        assert "json.dumps" in content
        assert "window.__GANKAIGC_RUNTIME__" in content
        assert "appVersion" in content
        assert "get_current_app_version()" in content
        assert "HTMLResponse" in content
        assert "text.replace(\"</head>\", runtime_script + \"</head>\", 1)" in content


def test_admin_invite_table_uses_compact_full_width_layout_like_credit_codes():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")

    assert 'table className="w-full table-auto divide-y divide-gray-200"' in admin_dashboard
    assert "min-w-[46rem]" not in admin_dashboard
    assert 'className="w-10 py-3 pr-4 whitespace-nowrap"' in admin_dashboard
    assert 'className="w-[26%] py-3 pr-4 whitespace-nowrap"' in admin_dashboard
    assert 'className="w-[9%] py-3 pr-4 whitespace-nowrap"' in admin_dashboard
    assert 'className="w-[20%] py-3 pr-4 whitespace-nowrap"' in admin_dashboard
    assert 'className="w-[20%] py-3 pr-4 whitespace-nowrap"' in admin_dashboard
    assert 'className="w-[7rem] py-3 pr-4 whitespace-nowrap"' in admin_dashboard


def test_admin_dashboard_hides_word_formatter_statistics_until_feature_is_ready():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")

    assert "statistics.word_formatter" not in admin_dashboard
    assert "排版任务" not in admin_dashboard
    assert "Word 排版任务" not in admin_dashboard


def test_database_manager_honors_backend_read_only_flag():
    database_manager = (FRONTEND_SRC / "components" / "DatabaseManager.jsx").read_text(encoding="utf-8")

    assert "canWrite" in database_manager
    assert "response.data.can_write" in database_manager
    assert "只读模式" in database_manager
    assert "canWrite && (" in database_manager
    assert "{canWrite && editingRecord && (" in database_manager


def test_admin_dashboard_does_not_duplicate_session_monitor_status_metrics():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")

    assert "data-admin-session-status" not in admin_dashboard
    assert "完成会话" not in admin_dashboard
    assert "排队等待" not in admin_dashboard
    assert "失败会话" not in admin_dashboard
    assert "完成进度" not in admin_dashboard
    assert "data-admin-processing-summary" in admin_dashboard
    assert "平均输入规模" in admin_dashboard


def test_admin_dashboard_shows_all_processing_mode_counts():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")

    assert "data-admin-processing-modes" in admin_dashboard
    assert "论文润色" in admin_dashboard
    assert "论文增强" in admin_dashboard
    assert "润色 + 增强" in admin_dashboard
    assert "感情文章润色" in admin_dashboard
    assert "processingStats.paper_polish_count" in admin_dashboard
    assert "processingStats.paper_enhance_count" in admin_dashboard
    assert "processingStats.paper_polish_enhance_count" in admin_dashboard
    assert "processingStats.emotion_polish_count" in admin_dashboard


def test_admin_dashboard_statistics_use_backend_range_and_real_series():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")

    assert "params: { range: dashboardDateRange }" in admin_dashboard
    assert "[isAuthenticated, dashboardDateRange]" in admin_dashboard
    assert "statistics.processing.series" in admin_dashboard or "processingStats.series" in admin_dashboard
    assert "processingStats.mode_rows" in admin_dashboard
    assert "mode.trend_percent" in admin_dashboard
    assert "statistics.sessions.success_rate" in admin_dashboard
    assert "processingSeries.success_rate" in admin_dashboard
    assert "statistics.requests?.in_range" in admin_dashboard
    assert "statistics.sessions.completed_in_range" in admin_dashboard
    assert "total_chars_processed_in_range" in admin_dashboard
    assert "avg_processing_time_in_range" in admin_dashboard
    assert "avg_input_chars" in admin_dashboard
    assert "getSeriesValues" in admin_dashboard
    assert "formatTrendPercent" in admin_dashboard
    assert "const bars = [64, 68, 82, 80, 86, 88, 92]" not in admin_dashboard
    assert "MINI_CHART_POINTS" not in admin_dashboard
    assert "statistics.sessions.total + Number(statistics.sessions.today" not in admin_dashboard
    assert "较上周 ▲ 15.78%" not in admin_dashboard
    assert "较上周 ▲ 14.11%" not in admin_dashboard
    assert "较上周 ▲ 0.21%" not in admin_dashboard
    assert "▲ 12.34%" not in admin_dashboard
    assert "▲ 8.21%" not in admin_dashboard
    assert "▼ -3.45%" not in admin_dashboard
    assert "▲ 15.67%" not in admin_dashboard
    assert "▼ -8.47%" not in admin_dashboard
    assert "▲ 16.28%" not in admin_dashboard
    assert "较上周</span>" not in admin_dashboard
    assert "较上周增长" not in admin_dashboard
    assert "'43%'" not in admin_dashboard
    assert "'72%'" not in admin_dashboard
    assert "'89%'" not in admin_dashboard


def test_admin_dashboard_uses_left_sidebar_navigation():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")

    assert 'data-admin-nav="sidebar"' in admin_dashboard
    assert 'data-admin-nav="top-tabs"' not in admin_dashboard
    assert "lg:grid-cols-[240px_minmax(0,1fr)]" in admin_dashboard
    assert "lg:min-h-[calc(100vh-8rem)]" in admin_dashboard


def test_admin_dashboard_uses_aurora_admin_theme():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")
    session_monitor = (FRONTEND_SRC / "components" / "SessionMonitor.jsx").read_text(encoding="utf-8")
    operations_panel = (FRONTEND_SRC / "components" / "AdminOperationsPanel.jsx").read_text(encoding="utf-8")
    database_manager = (FRONTEND_SRC / "components" / "DatabaseManager.jsx").read_text(encoding="utf-8")
    config_manager = (FRONTEND_SRC / "components" / "ConfigManager.jsx").read_text(encoding="utf-8")
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")

    assert "gank-app-page aurora-app-page aurora-admin-page" in admin_dashboard
    assert "apple-global-nav aurora-topbar aurora-admin-topbar" in admin_dashboard
    assert "aurora-admin-sidebar" in admin_dashboard
    assert "aurora-admin-nav-item-active" in admin_dashboard
    assert "aurora-admin-service-card" not in admin_dashboard
    assert "服务节点" not in admin_dashboard
    assert "handleAdminTabChange('operations')" not in admin_dashboard
    assert "aurora-admin-section-head" in admin_dashboard
    assert "用户管理" in admin_dashboard
    assert "公告" in admin_dashboard
    assert "操作日志" in admin_dashboard
    for label in ("ACCOUNT CONTROL", "BROADCAST", "AUDIT LEDGER"):
        assert label not in admin_dashboard
    assert "bg-gradient-to-r from-teal-600" not in admin_dashboard
    assert "bg-gradient-to-r from-indigo-600" not in admin_dashboard
    assert "activeClass" not in admin_dashboard
    assert "inactiveClass" not in admin_dashboard
    assert "aurora-admin-topbar-center" not in admin_dashboard
    assert "指标由面板实时采集" not in admin_dashboard
    assert "面板自动刷新" not in admin_dashboard
    assert "openAdminNotifications" not in admin_dashboard
    assert "auditNotificationLabel" not in admin_dashboard
    assert "BellDot" not in admin_dashboard
    assert "openGithubIssues" in admin_dashboard
    assert "打开 GitHub Issues" in admin_dashboard
    assert '<Github className="h-5 w-5" />' in admin_dashboard
    assert "openAdminHelp" not in admin_dashboard
    assert "打开帮助与反馈" not in admin_dashboard
    assert "topbarAdminLabel" not in admin_dashboard
    assert "topbarAvatarText" not in admin_dashboard
    assert "{topbarAdminLabel} · 退出" not in admin_dashboard
    assert '<span className="aurora-admin-avatar">A</span>' not in admin_dashboard
    assert '<span className="hidden sm:inline">退出</span>' in admin_dashboard

    for source in (session_monitor, operations_panel, database_manager, config_manager):
        assert "aurora-admin-section space-y-6" in source
        assert "aurora-admin-section-head" in source

    assert ".aurora-admin-page" in index_css
    assert "--admin-blue: #0066cc" in index_css
    assert ".aurora-admin-sidebar" in index_css
    assert ".aurora-admin-nav-item-active" in index_css
    assert ".aurora-admin-card" in index_css
    assert ".aurora-admin-input" in index_css
    assert ".aurora-admin-section-head" in index_css
    assert "aurora-admin-service-card" not in index_css
    assert "aurora-admin-service-link" not in index_css


def test_admin_sidebar_nav_items_keep_uniform_size_and_no_duplicate_service_node():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")

    assert "'aurora-admin-sidebar--plain'" in admin_dashboard
    assert "['database', 'audit'].includes(activeTab)" not in admin_dashboard
    assert "aurora-admin-sidebar--boxed" not in admin_dashboard
    assert "服务节点" not in admin_dashboard
    assert "查看服务节点详情" not in admin_dashboard
    assert "aurora-admin-service-card" not in admin_dashboard
    assert "aurora-admin-service-card" not in index_css
    assert "aurora-admin-service-link" not in index_css
    assert 'aurora-admin-page[data-admin-tab="audit"] .aurora-admin-nav-item-active' not in index_css
    assert 'aurora-admin-page[data-admin-tab="database"] .aurora-admin-nav-icon' not in index_css
    assert "aurora-admin-sidebar--plain .aurora-admin-nav-icon" in index_css
    assert "width: 28px" in index_css
    assert "height: 28px" in index_css


def test_system_config_api_guide_is_visible_in_aurora_admin_theme():
    config_manager = (FRONTEND_SRC / "components" / "ConfigManager.jsx").read_text(encoding="utf-8")
    api_guide = (FRONTEND_SRC / "components" / "ApiConfigGuide.jsx").read_text(encoding="utf-8")
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")
    static_index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    css_bundle_match = re.search(r'href="/assets/(index-[^"]+\.css)"', static_index)
    assert css_bundle_match
    static_css_bundle = (STATIC_DIR / "assets" / css_bundle_match.group(1)).read_text(encoding="utf-8")

    assert "ApiConfigGuide" in config_manager
    assert "aurora-config-guide-shell" in config_manager
    assert 'data-api-guide-multi-expand="true"' in api_guide

    guide_shell_block = re.search(r"\.aurora-config-guide-shell\s*\{(?P<body>[^}]*)\}", index_css)
    assert guide_shell_block
    assert "display: block" in guide_shell_block.group("body")
    assert "display: none" not in guide_shell_block.group("body")
    assert '.aurora-config-guide-shell > [data-api-guide-multi-expand="true"]' in index_css

    compact_static_css = re.sub(r"\s+", "", static_css_bundle)
    assert ".aurora-config-guide-shell{display:block}" in compact_static_css
    assert ".aurora-config-guide-shell{display:none}" not in compact_static_css
    assert ".aurora-config-guide-shell>[data-api-guide-multi-expand=true]" in compact_static_css


def test_admin_dashboard_exposes_operations_status_tab():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")
    operations_panel = (FRONTEND_SRC / "components" / "AdminOperationsPanel.jsx").read_text(encoding="utf-8")
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")

    assert "'operations'" in admin_dashboard
    assert "运维状态" in admin_dashboard
    assert "AdminOperationsPanel" in admin_dashboard
    assert 'data-admin-operations-panel="true"' in operations_panel
    assert "/api/admin/operations/status" in operations_panel
    assert "/api/admin/operations/backups/" in operations_panel
    assert "最近备份" in operations_panel
    assert "数据库" in operations_panel
    assert "版本更新" in operations_panel
    assert "手动 SSH" in operations_panel
    assert "源码更新" not in operations_panel
    assert "docker_socket_mounted" not in operations_panel
    assert "disabled_reason" not in operations_panel
    assert "status?.system?.cpu?.percent" in operations_panel
    assert "status?.system?.memory?.percent" in operations_panel
    assert "status?.system?.disk?.percent" in operations_panel
    assert "status?.system?.network?.rx_rate_label" in operations_panel
    assert "status?.system?.load?.load1" in operations_panel
    assert "status?.database?.average_latency_ms" in operations_panel
    assert "status?.database?.latency_samples_ms" in operations_panel
    assert "status?.models?.items" in operations_panel
    assert "status?.events" in operations_panel
    assert "OPS_STATUS_REFRESH_INTERVAL_MS = 5000" in operations_panel
    assert "isFetchingStatusRef" in operations_panel
    assert "document.visibilityState !== 'visible'" in operations_panel
    assert "document.addEventListener('visibilitychange'" in operations_panel
    assert "OPS_LATENCY_WINDOWS" in operations_panel
    assert "OPS_LATENCY_HISTORY_RETENTION_MS" in operations_panel
    assert "latencyWindowMs" in operations_panel
    assert "latencyHistory" in operations_panel
    assert "handleLatencyWindowChange" in operations_panel
    assert "fetchStatus({ silent: true, force: true })" in operations_panel
    assert "activeLatencyWindow" not in operations_panel
    assert "latencySampleCount" not in operations_panel
    assert "当前窗口" not in operations_panel
    assert "采样窗口，已刷新数据" not in operations_panel
    assert "已切换到" not in operations_panel
    assert "title={`切换到 ${windowOption.label} 采样窗口`}" not in operations_panel
    assert "aria-pressed={latencyWindowMs === windowOption.value}" in operations_panel
    assert "disabled={latencyWindowMs === windowOption.value}" not in operations_panel
    assert "aurora-ops-board-shell" in operations_panel
    assert "aurora-ops-reference-panel" in operations_panel
    assert "aurora-ops-score-reference-ring" in operations_panel
    assert "aurora-ops-window-tabs" in operations_panel
    assert "aurora-ops-reference-chart" in operations_panel
    assert "网络入站" in operations_panel
    assert "网络出站" in operations_panel
    assert "aurora-ops-score-ring" not in operations_panel
    assert "aurora-ops-score-orb" not in operations_panel
    assert ".aurora-ops-board-shell" in index_css
    assert ".aurora-ops-reference-panel" in index_css
    assert ".aurora-ops-score-reference-ring" in index_css
    assert ".aurora-ops-window-tabs" in index_css
    assert ".aurora-ops-info-title em" not in index_css
    assert ".aurora-ops-reference-chart" in index_css
    live_grid_block = re.search(r"\.aurora-ops-live-grid\s*\{(?P<body>[^}]*)\}", index_css)
    assert live_grid_block
    assert "grid-template-columns" in live_grid_block.group("body")
    assert "1 / -1" not in live_grid_block.group("body")
    reference_panel_block = re.search(r"\.aurora-ops-reference-panel\s*\{(?P<body>[^}]*)\}", index_css)
    assert reference_panel_block
    assert "min-height: 252px" in reference_panel_block.group("body")
    metric_grid_block = re.search(r"\.aurora-ops-metric-grid\s*\{(?P<body>[^}]*)\}", index_css)
    assert metric_grid_block
    assert "repeat(3" in metric_grid_block.group("body")
    runtime_grid_block = re.search(r"\.aurora-ops-runtime-grid\s*\{(?P<body>[^}]*)\}", index_css)
    assert runtime_grid_block
    assert "repeat(6" in runtime_grid_block.group("body")
    assert "Sub2API" in operations_panel
    assert "运维监控" in operations_panel
    assert "SLA" not in operations_panel
    assert "TTFT" not in operations_panel
    assert "QPS" not in operations_panel
    assert "99.060" not in operations_panel
    assert "Math.max(18" not in operations_panel
    assert "3.6 GB / 7.8 GB" not in operations_panel
    assert "↑ 1.2 MB/s ↓ 2.4 MB/s" not in operations_panel
    assert "2.42 ms" not in operations_panel
    assert "OpenAI (gpt-4o)" not in operations_panel
    assert "Moonshot (moonshot-v1-8k)" not in operations_panel
    assert "模型服务 OpenAI 恢复正常" not in operations_panel


def test_admin_dashboard_exposes_user_management_ban_controls():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")
    users_section = admin_dashboard.split("accountPanelTab === 'users'", 1)[1].split("accountPanelTab === 'creditTransactions'", 1)[0]

    assert "用户管理" in admin_dashboard
    assert "账号啤酒" not in admin_dashboard
    assert "handleToggleUserStatus" in admin_dashboard
    assert "/api/admin/users/${user.id}/toggle" in admin_dashboard
    assert "封禁" in admin_dashboard
    assert "解封" in admin_dashboard
    assert "已封禁" in admin_dashboard
    assert "window.confirm" in admin_dashboard
    assert "确认封禁用户" in admin_dashboard
    assert "ID #${user.id}" in admin_dashboard
    assert "Ban," in admin_dashboard
    assert "UserCheck" in admin_dashboard
    assert "aurora-admin-status-toggle" in users_section
    assert "is-danger" in users_section
    assert "is-restore" in users_section
    assert "aria-label={user.is_active ? '封禁用户' : '启用用户'}" in users_section
    assert '{user.is_active ? <Ban className="h-4 w-4" /> : <UserCheck className="h-4 w-4" />}' in users_section


def test_admin_user_management_polishes_layout_and_actions():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")
    accounts_section = admin_dashboard.split("{activeTab === 'accounts' && (", 1)[1].split("{activeTab === 'announcements' && (", 1)[0]
    users_section = admin_dashboard.split("accountPanelTab === 'users'", 1)[1].split("accountPanelTab === 'creditTransactions'", 1)[0]
    detail_panel = users_section.split('<aside className="aurora-admin-user-detail-panel">', 1)[1].split("</aside>", 1)[0]
    detail_header = users_section.split('<aside className="aurora-admin-user-detail-panel">', 1)[1].split("{highlightedUser ? (", 1)[0]

    assert "{accountPanelTab === 'users' && (" in admin_dashboard
    assert "<h2>用户管理</h2>" not in accounts_section
    assert "检索、筛选并管理用户资产、角色状态和最近活动。" not in accounts_section
    assert "aurora-admin-account-tabs-row" in accounts_section
    assert "aurora-admin-account-tab-list" in accounts_section
    assert accounts_section.index("aurora-admin-account-utility-tabs") < accounts_section.index("清除筛选")
    assert accounts_section.index("aurora-admin-account-tab-list") < accounts_section.index("aurora-admin-user-head-actions")
    assert "aurora-admin-tab-button-active bg-indigo-600 text-white shadow-sm" not in admin_dashboard
    assert "aurora-admin-users-filters" not in users_section
    assert "aurora-admin-user-filter-strip" in users_section
    assert "aurora-admin-user-filter-search" in users_section
    assert users_section.index("aurora-admin-user-filter-strip") < users_section.index("搜索用户名 / 邮箱 / UID")
    assert "aurora-admin-user-scope-tabs" not in users_section
    assert "近7天" not in users_section
    assert "['vip', 'VIP']" not in users_section
    assert "['blocked', '异常']" not in users_section

    assert "aurora-admin-icon-button" not in detail_header
    assert "MoreHorizontal" not in detail_header
    assert "aurora-admin-user-detail-only-list" in detail_panel
    assert "aurora-admin-user-profile-card" not in detail_panel
    assert "aurora-admin-user-assets" not in detail_panel
    assert "aurora-admin-user-actions" not in detail_panel
    assert "调整资产" not in detail_panel
    assert "封禁用户" not in detail_panel
    assert "启用用户" not in detail_panel
    assert "啤酒余额" not in detail_panel
    assert "最近登录" not in detail_panel
    assert "登录 IP" not in detail_panel
    assert "设备" not in detail_panel
    assert "累计用量" in admin_dashboard
    assert "邀请码" in admin_dashboard
    assert "模型配置" in admin_dashboard

    assert "w-full min-w-[1180px] divide-y divide-gray-200 aurora-admin-user-table" in users_section
    assert "aurora-admin-user-role-badge" in users_section
    assert "aurora-admin-user-vip-badge" not in users_section
    assert "aurora-admin-unlimited-toggle" in users_section
    assert "设无限" not in users_section
    assert "设为无限" in users_section
    assert "取消无限啤酒" in users_section
    assert "设为无限啤酒" in users_section
    assert 'CircleDollarSign className="h-4 w-4"' in users_section
    assert "<MoreHorizontal" not in users_section
    assert "啤酒余额" in users_section
    assert "余额 (Credits)" not in users_section
    assert "啤彩 (Beer)" not in users_section
    assert "啤酒 (Beer)" not in users_section
    assert 'colSpan="6"' in users_section
    assert 'colSpan="7"' not in users_section

    assert ".aurora-admin-user-table" in index_css
    assert ".aurora-admin-user-filter-search" in index_css
    assert "width: min(23rem, 28vw)" in index_css
    assert "aurora-admin-user-filter-export" in users_section
    assert ".aurora-admin-user-filter-export" in index_css
    assert "新增用户" not in users_section
    assert ".aurora-admin-user-role-badge" in index_css
    assert "white-space: nowrap" in index_css
    assert "writing-mode: horizontal-tb" in index_css
    assert ".aurora-admin-unlimited-toggle" in index_css
    assert "width: 6.35rem" in index_css
    assert ".aurora-admin-account-tabs-row" in index_css
    assert ".aurora-admin-status-toggle.is-danger" in index_css
    assert ".aurora-admin-user-detail-only-list" in index_css
    assert ".aurora-admin-user-scope-tabs" not in index_css


def test_admin_announcement_page_removes_redundant_header_and_keeps_icon_refresh():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")
    announcements_section = admin_dashboard.split("{activeTab === 'announcements' && (", 1)[1].split("{activeTab === 'database' && (", 1)[0]

    assert "aurora-admin-breadcrumb" not in announcements_section
    assert "<h2>公告</h2>" not in announcements_section
    assert "创建、管理和发布平台公告" not in announcements_section
    assert 'aria-label="刷新公告"' in announcements_section
    assert "aurora-admin-list-actions" in announcements_section
    assert "<RefreshCw" in announcements_section
    assert "aurora-admin-secondary-action" not in announcements_section
    assert ".aurora-admin-list-actions" in index_css


def test_admin_announcement_markdown_toolbar_is_functional_and_previewed():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")
    workspace = (FRONTEND_SRC / "pages" / "WorkspacePage.jsx").read_text(encoding="utf-8")
    markdown_preview = (FRONTEND_SRC / "components" / "MarkdownPreview.jsx").read_text(encoding="utf-8")
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")
    announcements_section = admin_dashboard.split("{activeTab === 'announcements' && (", 1)[1].split("{activeTab === 'database' && (", 1)[0]

    assert "ANNOUNCEMENT_MARKDOWN_TOOLS" in admin_dashboard
    assert "applyAnnouncementMarkdownTool" in admin_dashboard
    assert "announcementTextareaRef" in admin_dashboard
    assert "onClick={() => applyAnnouncementMarkdownTool(tool)}" in announcements_section
    assert "<span key={item}>{item}</span>" not in announcements_section
    assert "撤销 Markdown 编辑" in announcements_section
    assert "重做 Markdown 编辑" in announcements_section
    assert "展开 Markdown 编辑区" in announcements_section
    assert "<MarkdownPreview content={announcementContent}" in announcements_section
    assert "DEFAULT_ANNOUNCEMENT_MARKDOWN" in admin_dashboard
    assert "renderInlineMarkdown" in markdown_preview
    assert "renderMarkdownBlocks" in markdown_preview
    assert "isSafeMarkdownHref" in markdown_preview
    assert "dangerouslySetInnerHTML" not in markdown_preview
    assert "MarkdownPreview content={announcement.content}" in workspace
    assert ".aurora-admin-editor-toolbar button" in index_css
    assert ".aurora-markdown-preview" in index_css
    assert ".aurora-markdown-table-wrap" in index_css


def test_api_interceptor_clears_user_token_for_unauthorized_and_forbidden():
    api = (FRONTEND_SRC / "api" / "index.js").read_text(encoding="utf-8")

    assert "const status = error.response?.status" in api
    assert "status === 401 || status === 403" in api
    assert "localStorage.removeItem('userToken')" in api
    assert "window.location.pathname.startsWith('/admin')" in api
    assert "window.location.href = '/login'" in api


def test_admin_dashboard_preserves_selected_tab_in_url():
    admin_dashboard = (FRONTEND_SRC / "pages" / "AdminDashboard.jsx").read_text(encoding="utf-8")

    assert "useSearchParams" in admin_dashboard
    assert "searchParams.get('tab')" in admin_dashboard
    assert "setSearchParams" in admin_dashboard
    assert "handleAdminTabChange" in admin_dashboard
    assert "onClick={() => handleAdminTabChange(id)}" in admin_dashboard


def test_word_formatter_frontend_routes_and_api_are_removed_until_feature_is_ready():
    app = (FRONTEND_SRC / "App.jsx").read_text(encoding="utf-8")
    api = (FRONTEND_SRC / "api" / "index.js").read_text(encoding="utf-8")

    assert "WordFormatterPage" not in app
    assert "SpecGeneratorPage" not in app
    assert "ArticlePreprocessorPage" not in app
    assert "FormatCheckerPage" not in app
    assert 'path="/word-formatter"' not in app
    assert 'path="/spec-generator"' not in app
    assert 'path="/article-preprocessor"' not in app
    assert 'path="/format-checker"' not in app

    assert "wordFormatterAPI" not in api
    assert "/word-formatter" not in api

    for page_name in (
        "WordFormatterPage.jsx",
        "SpecGeneratorPage.jsx",
        "ArticlePreprocessorPage.jsx",
        "FormatCheckerPage.jsx",
    ):
        assert not (FRONTEND_SRC / "pages" / page_name).exists()


def test_word_formatter_backend_uses_platform_credits_or_user_api_not_legacy_card_key():
    routes = (PACKAGE_ROOT / "backend" / "app" / "word_formatter" / "routes.py").read_text(encoding="utf-8")

    assert "CreditService" in routes
    assert "ProviderConfigService" in routes
    assert "billing_mode" in routes
    assert "charge_word_formatter_platform_credit" in routes
    assert "get_word_formatter_ai_service" in routes
    assert "该卡密已达到使用次数限制" not in routes


def test_workspace_and_credits_explain_character_based_credit_billing():
    workspace = (FRONTEND_SRC / "pages" / "WorkspacePage.jsx").read_text(encoding="utf-8")
    credits_page = (FRONTEND_SRC / "pages" / "CreditsPage.jsx").read_text(encoding="utf-8")
    profile_page = (FRONTEND_SRC / "pages" / "ProfilePage.jsx").read_text(encoding="utf-8")
    welcome_page = (FRONTEND_SRC / "pages" / "WelcomePage.jsx").read_text(encoding="utf-8")
    readme = (PACKAGE_ROOT.parent / "README.md").read_text(encoding="utf-8")

    assert "1 啤酒 = 1000 非空白字符" in workspace
    assert "预计消耗 {estimatedCredits} 啤酒" in workspace
    assert "平台啤酒不足" in workspace
    assert "平台啤酒" in credits_page
    assert "BeerIcon" in credits_page
    assert "1000 个非空白字符" in credits_page
    assert "剩余啤酒" in profile_page
    assert "BeerIcon" in profile_page
    assert "按啤酒使用" in welcome_page
    assert "兑换码充值啤酒" in readme
    assert "平台模式按字符折算啤酒" in readme
    assert "千字额度" not in workspace
    assert "千字额度" not in credits_page
    assert "千字额度" not in profile_page
    assert "千字额度" not in welcome_page
    assert "兑换码充值次数" not in readme
    assert "平台次数模式" not in readme


def test_frontend_exposes_profile_page_and_nickname_update():
    app = (FRONTEND_SRC / "App.jsx").read_text(encoding="utf-8")
    user_menu = (FRONTEND_SRC / "components" / "UserMenu.jsx").read_text(encoding="utf-8")
    api = (FRONTEND_SRC / "api" / "index.js").read_text(encoding="utf-8")
    profile_page = (FRONTEND_SRC / "pages" / "ProfilePage.jsx").read_text(encoding="utf-8")

    assert 'path="/profile"' in app
    assert 'to="/profile"' in user_menu
    assert "个人信息" in user_menu
    assert "nickname" in profile_page
    assert "保存昵称" in profile_page
    assert "updateProfile" in api


def test_frontend_exposes_user_invite_generation_on_profile_page():
    api = (FRONTEND_SRC / "api" / "index.js").read_text(encoding="utf-8")
    profile_page = (FRONTEND_SRC / "pages" / "ProfilePage.jsx").read_text(encoding="utf-8")

    assert "getMyInvite" in api
    assert "createMyInvite" in api
    assert "/user/invites/my" in api
    assert "/user/invites" in api
    assert "我的邀请码" in profile_page
    assert "生成邀请码" in profile_page
    assert "复制邀请码" in profile_page
    assert "每个账号仅可生成 1 个邀请码" in profile_page
    assert "使用后可再次生成" not in profile_page


def test_frontend_removes_legacy_card_key_and_dead_prompt_manager():
    app = (FRONTEND_SRC / "App.jsx").read_text(encoding="utf-8")
    api = (FRONTEND_SRC / "api" / "index.js").read_text(encoding="utf-8")
    session_monitor = (FRONTEND_SRC / "components" / "SessionMonitor.jsx").read_text(encoding="utf-8")

    assert 'path="/access/:cardKey"' not in app
    assert not (FRONTEND_SRC / "components" / "PromptManager.jsx").exists()
    assert "export const promptsAPI" not in api
    assert "export const healthAPI" not in api
    assert "export const adminAPI" not in api
    assert "admin_password" not in api
    assert "adminAPI" not in session_monitor
    assert "prompt(" not in session_monitor
    assert "getSessionUserLabel" in session_monitor
    assert "session.user_display_name" in session_monitor
    assert "用户会话历史: {selectedUser.label}" in session_monitor
    assert "用户会话历史: {selectedUser.card_key}" not in session_monitor


def test_package_main_no_longer_registers_legacy_access_page():
    package_main = (PACKAGE_ROOT / "main.py").read_text(encoding="utf-8")

    assert '@app.get("/access/{card_key}")' not in package_main
    assert "async def serve_access" not in package_main


def test_session_export_modal_only_offers_word_and_markdown():
    session_detail = (FRONTEND_SRC / "pages" / "SessionDetailPage.jsx").read_text(encoding="utf-8")
    api = (FRONTEND_SRC / "api" / "index.js").read_text(encoding="utf-8")

    assert "useState('docx')" in session_detail
    assert '<option value="docx">Word文档 (.docx)</option>' in session_detail
    assert '<option value="md">Markdown文件 (.md)</option>' in session_detail
    assert '<option value="aigc_report_docx">AIGC检测报告 (.docx)</option>' in session_detail
    assert '<option value="aigc_report_md">AIGC检测报告 (.md)</option>' in session_detail
    assert "每一段的 AI 率" in session_detail
    assert 'value="txt"' not in session_detail
    assert 'value="pdf"' not in session_detail
    assert "即将支持" not in session_detail
    assert "content_base64" in session_detail
    assert "mime_type" in session_detail
    assert "responseType" not in api


def test_session_detail_shows_zhuque_report_and_process_timeline():
    session_detail = (FRONTEND_SRC / "pages" / "SessionDetailPage.jsx").read_text(encoding="utf-8")

    assert "朱雀 AI 报告" in session_detail
    assert "处理过程" in session_detail
    assert "zhuque_detect_result" in session_detail
    assert "全文检测" in session_detail
    assert "全文复检" in session_detail


def test_workspace_guides_zhuque_browser_launch_from_ai_detect_mode():
    workspace = (FRONTEND_SRC / "pages" / "WorkspacePage.jsx").read_text(encoding="utf-8")
    api = (FRONTEND_SRC / "api" / "index.js").read_text(encoding="utf-8")
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")
    zhuque_panel = workspace.split("aurora-zhuque-panel", 1)[1].split("aurora-editor-column", 1)[0]

    assert "朱雀 AI 检测" in zhuque_panel
    assert "扫码登录" in zhuque_panel
    assert "已登录" in zhuque_panel
    assert "剩余次数" in zhuque_panel
    assert "连接状态" in zhuque_panel
    assert "已连接" in workspace
    assert "未连接" in workspace
    assert "aurora-zhuque-status-card" in zhuque_panel
    assert "aurora-zhuque-title" in zhuque_panel
    assert "aurora-zhuque-title-icon" not in zhuque_panel
    assert "aurora-zhuque-metrics" in zhuque_panel
    assert "aurora-zhuque-login-button" in zhuque_panel
    assert "aurora-zhuque-logout-button" in zhuque_panel
    assert "handleLogoutZhuque" in workspace
    assert "logoutZhuque" in api
    assert "/optimization/zhuque/browser/logout" in api
    assert "handleRefreshZhuqueFreeQuota" in workspace
    assert "refreshZhuqueFreeQuota" in api
    assert "/optimization/zhuque/free-quota/refresh" in api
    assert zhuque_panel.index("朱雀 AI 检测") < zhuque_panel.index("aurora-zhuque-login-button")
    assert zhuque_panel.index("aurora-zhuque-login-button") < zhuque_panel.index("连接状态")
    assert zhuque_panel.index("连接状态") < zhuque_panel.index("剩余次数")
    assert "aurora-zhuque-account" in zhuque_panel
    assert "登录用户" in zhuque_panel
    assert "aurora-zhuque-login-modal" in workspace
    assert "aurora-zhuque-qr-frame" in workspace
    assert "qr_image_data" in workspace
    assert "每个 GankAIGC 用户独立保存朱雀凭证" in workspace
    assert "zhuqueAccountName" in workspace
    assert "zhuqueAccountLabel" in workspace
    assert "zhuqueConnected" in workspace
    assert "zhuqueRemainingLabel" in workspace
    assert ": '免费次数'" not in workspace
    assert "syncZhuqueLoggedOutSnapshot" in workspace
    assert "mergeZhuqueReadiness(preflight)" in workspace
    assert "朱雀免费检测次数可用" in workspace
    assert "disabled={isStartingZhuqueLogin}" in workspace
    assert "disabled={isStartingZhuqueLogin || zhuqueConnected}" not in workspace
    assert "startZhuqueLogin({ syncSession: true, mode: 'remote_qr' })" in workspace
    assert "setZhuqueFastPollUntil(Date.now() + ZHUQUE_STATUS_FAST_POLL_DURATION_MS)" in workspace
    assert "response.data?.switch_account" not in workspace
    assert "params: { sync_session: syncSession, mode }" in api
    assert "params: { switch_account: switchAccount }" not in api
    assert "朱雀已登录；如需换号或使用未登录免费次数，请点退出" in workspace
    assert "回到未登录免费次数路径" in workspace
    assert "在当前页面打开朱雀微信扫码二维码" in workspace
    assert "startZhuqueBrowser" in workspace
    assert "zhuqueLoginSession" in workspace
    assert "getZhuqueLoginStatus" in workspace
    assert "cancelZhuqueLogin" in workspace
    assert "未登录也可使用朱雀免费次数" not in zhuque_panel
    assert "次数不足时请登录或切换账号" not in zhuque_panel
    assert "可在下方一键启动朱雀检测浏览器" not in zhuque_panel
    assert "需先按后端配置端口启动" not in workspace
    assert ".aurora-zhuque-status-card" in index_css
    assert ".aurora-zhuque-metric" in index_css
    assert ".aurora-zhuque-login-button" in index_css
    assert ".aurora-zhuque-logout-button" in index_css
    assert ".aurora-zhuque-quota-refresh" in index_css
    assert ".aurora-zhuque-account" in index_css
    assert ".aurora-zhuque-login-modal" in index_css
    assert ".aurora-zhuque-qr-frame" in index_css
    assert ".aurora-zhuque-login-stat" in index_css
    assert "grid-template-columns: minmax(9.5rem" not in index_css
    assert "flex-wrap: wrap" in index_css
    assert "font-size: 14px;" in index_css
    assert (
        ".aurora-zhuque-title p {\n"
        "  color: #0f172a;\n"
        "  font-size: 18px;\n"
        "  font-family: inherit;\n"
        "  font-weight: 600;"
    ) in index_css
    zhuque_css = index_css.split(".aurora-zhuque-status-card", 1)[1].split("@media (max-width: 640px)", 1)[0]
    assert ".aurora-zhuque-login-button {" in zhuque_css
    assert "font-weight: 600;\n  letter-spacing: -0.01em;" in zhuque_css
    assert "font-weight: 860;" not in zhuque_css
    assert "font-weight: 850;" not in zhuque_css
    assert "order: 1;" in zhuque_css
    assert "--zhuque-card-gap: 0.72rem;" in index_css
    assert "gap: var(--zhuque-card-gap);" in index_css
    assert ".aurora-zhuque-title {\n  display: inline-flex;\n  flex: 0 0 auto;" in index_css
    assert "flex: 1 1 9.2rem;" not in index_css
    assert "display: contents;" in index_css
    assert "flex: 999 1 18.2rem;" not in index_css
    assert ".aurora-zhuque-metrics .aurora-zhuque-metric:first-child" in index_css
    assert "@media (max-width: 1180px)" not in index_css
    assert "startZhuqueBrowser" in api
    assert "getZhuqueBrowserStatus" in api
    assert "/optimization/zhuque/browser/start" in api
    assert "/optimization/zhuque/browser/status" in api
    assert "/optimization/zhuque/browser/login-status" in api
    assert "/optimization/zhuque/browser/cancel" in api


def test_workspace_shows_zhuque_readiness_and_preflight_agent_state():
    workspace = (FRONTEND_SRC / "pages" / "WorkspacePage.jsx").read_text(encoding="utf-8")
    api = (FRONTEND_SRC / "api" / "index.js").read_text(encoding="utf-8")
    zhuque_panel = workspace.split("aurora-zhuque-panel", 1)[1].split("aurora-editor-column", 1)[0]

    assert "getZhuqueReadiness" in api
    assert "preflightZhuqueTask" in api
    assert "/optimization/zhuque/readiness" in api
    assert "/optimization/zhuque/preflight" in api
    assert "zhuqueReadiness" in workspace
    assert "loadZhuqueReadiness" in workspace
    assert "preflightZhuqueTask" in workspace
    assert "连接状态" in zhuque_panel
    assert "剩余次数" in zhuque_panel
    assert "页面状态" not in zhuque_panel
    assert "文本长度" not in zhuque_panel
    assert "认证方式" not in zhuque_panel
    assert "预计最多消耗" not in zhuque_panel
    assert "extractZhuqueRemainingUses" in workspace
    assert "zhuqueLastKnownLoggedOutRemaining" in workspace
    assert "source.remaining_uses" in workspace
    assert "source.remainingUses" in workspace
    assert "source.quota_text" in workspace
    assert "const zhuqueHasKnownRemaining = zhuqueRemainingValue !== undefined" in workspace
    assert "? formatZhuqueRemainingUses(zhuqueRemainingValue)" in workspace
    assert ": '检测后同步'" in workspace
    assert ": zhuqueConnected ? '检测后同步' : '免费次数'" not in workspace
    assert "const zhuqueRemainingValue = zhuqueConnected" not in workspace
    assert "clearZhuqueLoggedOutRemaining" in workspace
    assert "remaining === undefined && response.data?.connected === false" in workspace
    assert "response.data?.button_enabled || response.data?.ready" in workspace
    assert "朱雀免费检测入口可用，剩余次数将在检测后同步" in workspace
    assert "检测后同步|未知|不可用" in workspace


def test_session_detail_shows_zhuque_agent_trace():
    session_detail = (FRONTEND_SRC / "pages" / "SessionDetailPage.jsx").read_text(encoding="utf-8")

    assert "zhuque_agent_trace" in session_detail
    assert "Agent 决策轨迹" in session_detail
    assert "parseZhuqueAgentTrace" in session_detail
    assert "zhuque_detect" in session_detail
    assert "zhuque_reduce" in session_detail
    assert "命中段落" in session_detail
    assert "风险率变化" in session_detail
    assert "诊断建议" in session_detail
    assert "shouldShowResultSwitch()" not in session_detail
    assert "collapsedZhuqueEventKeys" in session_detail
    assert "toggleZhuqueEvent" in session_detail
    assert "aria-expanded" in session_detail
    assert "aria-controls" in session_detail
    assert "aurora-agent-chevron-placeholder" in session_detail
    assert "收敛反思" in session_detail
    assert "顽固段落" in session_detail
    assert "stubborn_segment_indices" in session_detail
    assert "Agent 学习结果" in session_detail
    assert "prompt_evolution" in session_detail
    assert "prompt_patch" in session_detail
    assert "length_adjustments" in session_detail
    assert "长度校正" in session_detail
    assert "rewrite_mode" in session_detail
    assert "逃逸改写" in session_detail
    assert "paper_reconstruction" in session_detail
    assert "论文重构" in session_detail
    assert "paper_language" in session_detail
    assert "paper_section" in session_detail
    assert "paper_ai_patterns" in session_detail
    assert "candidate_count" in session_detail
    assert "fact_card_count" in session_detail
    assert "rollback_applied" in session_detail
    assert "回滚保护" in session_detail
    assert "max-h-[560px]" in session_detail
    assert "custom-scrollbar" in session_detail
    assert "plateau_exit" in session_detail
    assert "卡点退出" in session_detail


def test_api_config_guide_lists_current_model_recommendations():
    api_guide = (FRONTEND_SRC / "components" / "ApiConfigGuide.jsx").read_text(encoding="utf-8")

    for model_name in [
        "gpt-5.5",
        "gpt-5.4",
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "deepseek-v4-pro",
        "deepseek-v4-flash",
    ]:
        assert model_name in api_guide

    for legacy_model_name in [
        "gemini-2.5-pro",
        "gemini-3-pro-preview",
        "claude-sonnet-4-20250514",
        "deepseek-chat",
        "gpt-5.2",
    ]:
        assert legacy_model_name not in api_guide


def test_config_manager_uses_current_model_placeholders():
    config_manager = (FRONTEND_SRC / "components" / "ConfigManager.jsx").read_text(encoding="utf-8")

    assert config_manager.count('placeholder="gpt-5.5"') == 4
    assert 'placeholder="gemini-2.5-pro"' not in config_manager


def test_config_manager_separates_sub_model_gateway_from_zhuque_detector():
    config_manager = (FRONTEND_SRC / "components" / "ConfigManager.jsx").read_text(encoding="utf-8")
    admin_routes = (PACKAGE_ROOT / "backend" / "app" / "routes" / "admin.py").read_text(encoding="utf-8")

    assert "模型中转站配置" in config_manager
    assert "Sub API 中转站" in config_manager
    assert "OpenAI Compatible 中转站" in config_manager
    assert "朱雀只负责腾讯 AI 率检测，不作为模型提供商" in config_manager
    assert 'placeholder="https://your-sub-domain/v1"' in config_manager
    assert "primaryBaseUrl" in config_manager
    assert "腾讯朱雀 AI 率检测" in config_manager
    assert "检测入口" in config_manager
    assert "不是模型提供商" in config_manager
    assert "loadZhuqueReadiness" in config_manager
    assert "/api/admin/zhuque/readiness" in config_manager
    assert "刷新朱雀检测状态" in config_manager
    assert "get_admin_zhuque_readiness" in admin_routes
    assert '@router.get("/zhuque/readiness")' in admin_routes
    assert "zhuque_service.readiness()" in admin_routes

    assert "ZhuQue（朱雀）</option>" not in config_manager
    assert "zhuque-70b-chat" not in config_manager
    assert "api.zhuque-ai.com" not in config_manager
    assert "ZhuQue 模型服务运行正常" not in config_manager
    assert "可用模型数" not in config_manager
    assert "速率限制状态" not in config_manager


def test_config_manager_system_config_layout_matches_aurora_actions():
    config_manager = (FRONTEND_SRC / "components" / "ConfigManager.jsx").read_text(encoding="utf-8")
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")

    assert "applyUnifiedModel" in config_manager
    assert "applyUnifiedBaseUrl" in config_manager
    assert "applyUnifiedApiKey" in config_manager
    assert "EMOTION_MODEL: modelName" in config_manager
    assert "COMPRESSION_MODEL: modelName" in config_manager
    assert "EMOTION_BASE_URL: baseUrl" in config_manager
    assert "COMPRESSION_BASE_URL: baseUrl" in config_manager
    assert "EMOTION_API_KEY: apiKey" in config_manager
    assert "COMPRESSION_API_KEY: apiKey" in config_manager
    assert "统一同步论文润色、原创性增强、情感文章和历史压缩" in config_manager

    for class_name in [
        "aurora-config-title-icon-gateway",
        "aurora-config-title-icon-security",
        "aurora-config-title-icon-quota",
        "aurora-config-title-icon-zhuque",
    ]:
        assert class_name in config_manager
        assert f".{class_name}" in index_css

    assert "Route" in config_manager
    assert "Fingerprint" in config_manager
    assert "Gauge" in config_manager
    assert "ScanSearch" in config_manager
    assert "aurora-config-timeout-field" in config_manager
    assert ".aurora-config-timeout-field" in index_css
    assert "grid-template-columns: max-content 5.25rem max-content" in index_css
    assert "justify-content: start" in index_css

    assert "aurora-config-bottom-bar" in config_manager
    assert "aurora-config-save-note" in config_manager
    assert ".aurora-config-bottom-bar" in index_css
    assert ".aurora-config-save-note" in index_css
    assert "bg-green-50/50 border border-green-100 rounded-xl p-4" not in config_manager

    section_head_source = config_manager.split('<div className="aurora-config-guide-shell">')[0]
    assert 'className="aurora-admin-action"' not in section_head_source
    assert config_manager.count("保存配置") == 1

    assert "微信扫码登录后用于腾讯朱雀 AI 检测" not in config_manager
    assert "次数由腾讯朱雀检测页返回，不消耗平台啤酒" not in config_manager
    assert "用于 AI 率检测/复检，不是模型提供商" not in config_manager
    assert "通过工作台扫码捕获凭证" not in config_manager
    assert "aurora-config-mono-value" in config_manager
    assert ".aurora-config-mono-value" in index_css




def test_config_manager_security_card_uses_real_settings_not_fake_switches():
    config_manager = (FRONTEND_SRC / "components" / "ConfigManager.jsx").read_text(encoding="utf-8")
    admin_routes = (PACKAGE_ROOT / "backend" / "app" / "routes" / "admin.py").read_text(encoding="utf-8")
    index_css = (FRONTEND_SRC / "index.css").read_text(encoding="utf-8")
    security_card = config_manager.split("aurora-config-security-card", 1)[1].split("aurora-config-quota-card", 1)[0]
    feature_card = config_manager.split("aurora-config-feature-card", 1)[1].split("aurora-config-advanced-drawer", 1)[0]

    assert "ACCESS_TOKEN_EXPIRE_MINUTES" in config_manager
    assert "USER_ACCESS_TOKEN_EXPIRE_MINUTES" in config_manager
    assert "AUTH_RATE_LIMIT_PER_MINUTE" in config_manager
    assert "REDEEM_RATE_LIMIT_PER_MINUTE" in config_manager
    assert "response.data.security?.admin_token_expire_minutes" in config_manager
    assert "response.data.security?.user_token_expire_minutes" in config_manager
    assert "response.data.security?.auth_rate_limit_per_minute" in config_manager
    assert "response.data.security?.redeem_rate_limit_per_minute" in config_manager
    assert "后台令牌有效期" in config_manager
    assert "用户令牌有效期" in config_manager
    assert "登录限流" in config_manager
    assert "兑换限流" in config_manager
    assert "模型 Base URL 安全校验" in config_manager
    assert "控制登录有效期、接口限流和模型地址安全校验" in security_card
    assert "登录后浏览器会拿到访问令牌" in security_card
    assert "管理员登录多久后需要重新登录" in security_card
    assert "同一 IP 每分钟最多尝试登录/注册多少次" in security_card
    assert "同一 IP 每分钟最多兑换多少次" in security_card
    assert "只在本机运行 GankAIGC" in security_card
    assert "公网部署不要打开" in security_card
    assert "aria-pressed={Boolean(formData.ALLOW_LOCAL_MODEL_PROXY)}" in security_card
    assert "ALLOW_LOCAL_MODEL_PROXY: !formData.ALLOW_LOCAL_MODEL_PROXY" in security_card
    assert "aurora-config-local-proxy-status" in security_card
    assert "当前 SERVER_HOST 为" in security_card
    assert "aurora-config-state-chip" in config_manager
    assert ".aurora-config-state-chip" in index_css
    assert ".aurora-config-local-proxy-line" in index_css
    assert ".aurora-config-server-host-field" in index_css
    assert ".aurora-config-local-proxy-status" in index_css
    assert '["本地模型代理", "仅本机部署时允许 HTTP 代理", "ALLOW_LOCAL_MODEL_PROXY"]' not in config_manager
    assert "['本地模型代理', '仅本机部署时允许 HTTP 代理', 'ALLOW_LOCAL_MODEL_PROXY']" not in config_manager
    assert "本地模型代理" not in feature_card

    assert 'value="24" readOnly' not in config_manager
    assert "强制 HTTPS" not in config_manager
    assert "IP 访问白名单" not in config_manager
    assert "敏感操作二次确认" not in config_manager
    assert "HTTPS 和敏感操作确认策略" not in config_manager
    assert 'placeholder="每行一个 IP 或网段，留空表示允许所有"' not in config_manager

    assert '"security": {' in admin_routes
    assert '"admin_token_expire_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES' in admin_routes
    assert '"user_token_expire_minutes": settings.USER_ACCESS_TOKEN_EXPIRE_MINUTES' in admin_routes
    assert '"auth_rate_limit_per_minute": settings.AUTH_RATE_LIMIT_PER_MINUTE' in admin_routes
    assert '"redeem_rate_limit_per_minute": settings.REDEEM_RATE_LIMIT_PER_MINUTE' in admin_routes

def test_config_manager_hides_word_formatter_file_size_setting_until_feature_is_ready():
    config_manager = (FRONTEND_SRC / "components" / "ConfigManager.jsx").read_text(encoding="utf-8")

    assert "Word 排版文件大小限制" not in config_manager
    assert "MAX_UPLOAD_FILE_SIZE_MB" not in config_manager
    assert "max_upload_file_size_mb" not in config_manager
    assert "0 表示无限制" not in config_manager


def test_config_manager_exposes_registration_enabled_switch():
    config_manager = (FRONTEND_SRC / "components" / "ConfigManager.jsx").read_text(encoding="utf-8")

    assert "REGISTRATION_ENABLED" in config_manager
    assert "账号注册控制" in config_manager
    assert "允许新用户通过邀请码注册" in config_manager
    assert "response.data.system.registration_enabled" in config_manager


def test_config_manager_exposes_admin_model_connection_tests():
    config_manager = (FRONTEND_SRC / "components" / "ConfigManager.jsx").read_text(encoding="utf-8")

    assert "/api/admin/operations/model-test" in config_manager
    assert "handleTestModel" in config_manager
    assert "renderTestButton" in config_manager
    assert "测试连接" in config_manager
    assert "handleTestModel(stage)" in config_manager
    assert "renderTestButton('polish')" in config_manager
    assert "renderTestButton('enhance')" in config_manager
    assert "renderTestButton('emotion')" in config_manager
    assert "renderTestButton('compression')" in config_manager


def test_api_config_guide_keeps_previous_sections_open_when_expanding_next():
    api_guide = (FRONTEND_SRC / "components" / "ApiConfigGuide.jsx").read_text(encoding="utf-8")

    assert "activeSections.includes(id)" in api_guide
    assert "setActiveSections((previousSections)" in api_guide
    assert "previousSections.filter((sectionId) => sectionId !== id)" in api_guide
    assert "return [...previousSections, id]" in api_guide
    assert "activeSection === id" not in api_guide
    assert "setActiveSection(isActive ? null : id)" not in api_guide
    assert 'data-api-guide-multi-expand="true"' in api_guide
    assert api_guide.count('type="button"') >= 3


def test_api_config_guide_preserves_scroll_position_when_toggling_sections():
    api_guide = (FRONTEND_SRC / "components" / "ApiConfigGuide.jsx").read_text(encoding="utf-8")

    assert "preserveScrollPosition" in api_guide
    assert "window.requestAnimationFrame" in api_guide
    assert "window.scrollTo(scrollX, scrollY)" in api_guide
    assert "preserveScrollPosition(() => {" in api_guide


def test_api_config_guide_links_to_current_project_issues():
    api_guide = (FRONTEND_SRC / "components" / "ApiConfigGuide.jsx").read_text(encoding="utf-8")

    assert "https://github.com/mumu-0922/GankAIGC/issues" in api_guide
    assert "https://github.com/chi111i/GankAIGC/issues" not in api_guide


def test_frontend_examples_avoid_secret_scanner_key_prefixes():
    api_guide = (FRONTEND_SRC / "components" / "ApiConfigGuide.jsx").read_text(encoding="utf-8")
    config_manager = (FRONTEND_SRC / "components" / "ConfigManager.jsx").read_text(encoding="utf-8")
    static_bundle = _read_static_js_assets()
    google_key_prefix = "AI" + "za"

    for source in (api_guide, config_manager, static_bundle):
        assert google_key_prefix not in source

    assert "Google API Key" in api_guide
    assert "Google API Key" in config_manager


def test_served_static_bundle_includes_api_guide_interaction_fix():
    static_bundle = _read_static_js_assets()

    assert "data-api-guide-multi-expand" in static_bundle
    assert "gemini-3.1-pro-preview" in static_bundle
    assert "gpt-5.5" in static_bundle
    assert "requestAnimationFrame" in static_bundle
    assert "scrollTo" in static_bundle
    assert "https://github.com/mumu-0922/GankAIGC/issues" in static_bundle
    assert "https://github.com/chi111i/GankAIGC/issues" not in static_bundle


def test_served_static_bundle_includes_admin_tab_url_persistence():
    static_bundle = _read_static_js_assets()

    assert "URLSearchParams" in static_bundle
    assert '"tab"' in static_bundle
    assert '"dashboard","operations","sessions","accounts","announcements","database","config"' in static_bundle
    assert "Word 排版文件大小限制" not in static_bundle
    assert "MAX_UPLOAD_FILE_SIZE_MB" not in static_bundle
    assert "max_upload_file_size_mb" not in static_bundle
    assert "排版任务" not in static_bundle


def test_served_static_bundle_includes_ai_reduction_homepage():
    static_bundle = _read_static_js_assets()

    assert "让论文原创更简单" in static_bundle
    assert "登录 / 注册" in static_bundle
    assert "优化前" in static_bundle
    assert "优化后" in static_bundle
    assert "AI 率检测结果" in static_bundle
    assert "data-home-scenarios" in static_bundle
    assert "论文处理链路" in static_bundle
    assert "阶段 01" in static_bundle
    assert "从初稿到投稿前的三步优化" in static_bundle
    assert "阶段 04" not in static_bundle
    assert "兑换码充值啤酒" in static_bundle
    assert "啤酒与自带 API 双模式" in static_bundle
    assert "千字额度" not in static_bundle
    assert "兑换码充值额度" not in static_bundle
    assert "有自有模型额度时，可切换为自带 API 模式" not in static_bundle
    assert "账号次数与自带 API 双模式" not in static_bundle
    assert "论文原创性工作台" not in static_bundle
    assert "功能介绍" not in static_bundle
    assert "使用场景" not in static_bundle
    assert "安全保障" not in static_bundle
    assert "https://github.com/mumu-0922/GankAIGC" in static_bundle
    assert "GitHub 项目" in static_bundle
    assert "求 Star" in static_bundle
    assert "data-home-github-star" in static_bundle

def test_session_monitor_uses_real_statistics_not_fake_placeholders():
    session_monitor = (FRONTEND_SRC / "components" / "SessionMonitor.jsx").read_text(encoding="utf-8")

    assert "/api/admin/statistics" in session_monitor
    assert "params: { range: statsRange }" in session_monitor
    assert "statistics?.processing?.series?.sessions" in session_monitor
    assert "statisticsRangeOptions" in session_monitor
    assert 'value="today"' in session_monitor or "value: 'today'" in session_monitor
    assert 'value="7d"' in session_monitor or "value: '7d'" in session_monitor
    assert 'value="30d"' in session_monitor or "value: '30d'" in session_monitor
    assert "formatTrendPercent(statistics?.requests?.trend_percent)" in session_monitor
    assert "statistics?.sessions?.success_rate" in session_monitor
    assert "statistics?.processing?.avg_processing_time_in_range" in session_monitor
    assert "allQueueSessions.length" in session_monitor
    assert "当前没有排队中的会话" in session_monitor
    assert "暂无最近任务" in session_monitor
    assert "已加载 {rawSessionsToRender.length} 条" in session_monitor
    assert "当前显示 {sessionsToRender.length} 条" in session_monitor

    forbidden_literals = [
        "较昨日 +18%",
        "较昨日 +12%",
        "较昨日 -8%",
        "较昨日 +0.42%",
        "1.28",
        "* 37",
        "queuedCount || 6",
        "|| 6",
        "共 12 个模型",
        "请求数 2,431",
        "今日 00:00 ~ 23:59",
        "每页 10 条",
    ]
    for literal in forbidden_literals:
        assert literal not in session_monitor

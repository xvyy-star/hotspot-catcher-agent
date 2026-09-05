<template>
  <a v-if="authChecked && isAuthenticated" class="skip-link" href="#main-content">跳到主要内容</a>
  <LoginPage
    v-if="authChecked && !isAuthenticated"
    @login-success="handleLoginSuccess"
    @error="setError"
    @set-loading="loading = $event"
  />

  <div v-else-if="authChecked" class="app-shell">
    <button
      v-if="mobileMenuOpen"
      class="mobile-sidebar-backdrop"
      type="button"
      aria-label="关闭导航"
      @click="closeMobileMenu"
    ></button>
    <aside
      id="app-sidebar"
      ref="mobileSidebarRef"
      :class="['sidebar', { collapsed, 'mobile-open': mobileMenuOpen }]"
      aria-label="主导航"
      @keydown.esc.stop.prevent="closeMobileMenu"
      @keydown.tab="trapMobileMenuFocus"
    >
      <div class="logo-row">
        <Settings style="color: var(--color-primary); width: 24px; height: 24px; flex-shrink: 0;" />
        <div class="logo-text">
          <div class="logo-name">热点捕手</div>
          <div class="logo-subtitle">情报运营工作台</div>
        </div>
      </div>
      <nav class="nav-list">
        <template v-for="(item, index) in navItems" :key="item.key">
          <div
            v-if="index === 0 || item.group !== navItems[index - 1]?.group"
            class="nav-section-label"
          >
            {{ item.group === 'core' ? '核心工作台' : '管理与诊断' }}
          </div>
          <button
            type="button"
            :class="['nav-btn', { active: activePage === item.key }]"
            @click="switchPage(item.key)"
          >
            <component :is="item.icon" />
            <span class="nav-text">{{ item.label }}</span>
          </button>
        </template>
      </nav>
      <div class="sidebar-footer app-note">
        <b>工作流主线</b>
        <p>数据源采集 → 清洗分类 → 分析聚合 → 知识入库 → 机器人推送</p>
      </div>
      <div class="sidebar-toggle-row">
        <ThemeToggle variant="sidebar" :collapsed="collapsed" />
        <button class="toggle-sidebar-btn" type="button" :title="collapsed ? '展开侧边栏' : '折叠侧边栏'" @click="collapsed = !collapsed">
          <Menu />
        </button>
      </div>
    </aside>

    <main id="main-content" class="main-area" tabindex="-1">
      <header class="topbar">
        <div class="topbar-left">
          <button
            ref="mobileMenuButtonRef"
            class="mobile-menu-btn"
            type="button"
            aria-label="打开导航"
            aria-controls="app-sidebar"
            :aria-expanded="mobileMenuOpen"
            @click="openMobileMenu"
          >
            <Menu />
          </button>
          <div class="topbar-title">
            <h1 class="page-title">{{ currentNav.label }}</h1>
          </div>
        </div>
        <div class="top-actions">
          <button class="user-chip" type="button" @click="switchPage('profile')">
            <span class="user-avatar">{{ currentUser?.avatar_text || 'HA' }}</span>
            <span class="user-chip-text">{{ currentUser?.display_name || '管理员' }}</span>
          </button>
          <button class="ghost-btn" type="button" :disabled="loading" @click="refreshCurrentPage">
            <RefreshCw :class="{ spinning: loading }" /> 刷新
          </button>
          <button
            v-if="activePage === 'dashboard' || activePage === 'events' || activePage === 'history' || activePage === 'setup'"
            class="primary-btn"
            type="button"
            :disabled="generating"
            @click="handleGenerate"
          >
            <Sparkles /> {{ generating ? '生成中...' : '生成今日早报' }}
          </button>
        </div>
      </header>

      <section class="content">


        <Transition name="fade-slide" mode="out-in">
          <div :key="activePage">
            <!-- Dashboard Page -->
            <section v-if="activePage === 'dashboard'">
              <div class="decision-hero card">
                <div class="decision-copy">
                  <span class="section-label">今日概览</span>
                  <h2>{{ todayBriefing ? '今日早报已生成' : '今日早报待生成' }}</h2>
                  <p>
                    {{ todayBriefing
                      ? `已汇总 ${dashboardEvents.length} 条带来源证据的热点，可继续复制、推送或写入知识库。`
                      : `已加载 ${dashboardEvents.length} 条最近事件预览，生成早报后可进入正式分发流程。` }}
                  </p>
                </div>
                <button class="ghost-btn" type="button" :disabled="loading" @click="switchPage('events')">
                  <Flame /> 查看热点池
                </button>
                <div class="decision-score">
                  <span :class="['badge', deliveryGrade.level]">{{ deliveryGrade.label }}</span>
                  <strong>{{ deliveryGrade.score }}</strong>
                  <small>{{ deliveryGrade.hint }}</small>
                </div>
              </div>

              <div class="insight-grid">
                <div v-for="item in executiveInsights" :key="item.title" class="insight-card">
                  <div :class="['insight-icon', item.tone]">
                    <component :is="item.icon" />
                  </div>
                  <div>
                    <b>{{ item.title }}</b>
                    <p>{{ item.desc }}</p>
                  </div>
                </div>
              </div>

              <div v-if="setupCompletion.percent < 100" class="setup-nudge">
                <div>
                  <b>{{ setupNudgeTitle }}</b>
                  <p>{{ setupNudgeDesc }}</p>
                </div>
                <button class="ghost-btn" type="button" @click="switchPage('setup')">打开首次引导</button>
              </div>

              <div class="stat-grid">
                <div class="card stat-card card-blue">
                  <p class="stat-label"><Newspaper /> 今日早报</p>
                  <p class="stat-value">{{ todayBriefing ? statusLabel(todayBriefing.status) : '未生成' }}</p>
                  <p class="stat-hint">{{ todayBriefing?.briefing_date || today }}</p>
                </div>
                <div class="card stat-card card-amber">
                  <p class="stat-label"><Flame /> 热点数量</p>
                  <p class="stat-value">{{ dashboardEvents.length }}</p>
                  <p class="stat-hint">{{ todayBriefing ? '今日早报事件' : '最近事件预览' }}</p>
                </div>
                <div class="card stat-card card-red">
                  <p class="stat-label"><AlertTriangle /> 高风险</p>
                  <p class="stat-value">{{ highRiskCount }}</p>
                  <p class="stat-hint">用于舆情提醒</p>
                </div>
                <div class="card stat-card card-green">
                  <p class="stat-label"><ShieldCheck /> 采集源</p>
                  <p class="stat-value">{{ sourceHealth?.enabled_sources ?? '-' }}</p>
                  <p class="stat-hint">健康源数量</p>
                </div>
                <div class="card stat-card card-purple">
                  <p class="stat-label"><DatabaseZap /> 知识库</p>
                  <p class="stat-value">{{ statusLabel(knowledgeHealth?.status) }}</p>
                  <p class="stat-hint">Qdrant/RAG</p>
                </div>
                <div class="card stat-card card-teal">
                  <p class="stat-label"><Clock3 /> 最近任务</p>
                  <p class="stat-value">{{ statusLabel(runs[0]?.status) }}</p>
                  <p class="stat-hint">{{ formatDateTime(runs[0]?.started_at) }}</p>
                </div>
              </div>

              <div class="two-col">
                <div class="briefing-card-wrapper">
                  <div class="card intelligence-panel">
                    <div class="intelligence-head">
                      <div>
                        <span class="section-label">{{ todayBriefing ? '今日简报' : '事件预览' }}</span>
                        <h2>{{ todayBriefing ? '今日热点情报' : '热点池预览（尚未生成今日早报）' }}</h2>
                        <p>{{ todayBriefing ? '卡片化展示结论、证据链接、可信度和建议动作；复制/推送仍使用完整 Markdown。' : '以下为数据库中的最近真实事件，仅用于预览；生成今日早报后才可复制、推送或写入知识库。' }}</p>
                      </div>
                      <div class="intelligence-actions">
                        <span :class="['badge', todayBriefing ? 'low' : 'medium']">
                          {{ todayBriefing?.status || '预览' }}
                        </span>
                        <button class="ghost-btn compact" type="button" :disabled="!todayBriefing" @click="copyText(briefingMarkdown)"><FileText /> 复制 Markdown</button>
                      </div>
                    </div>

                    <div v-if="!intelligenceCards.length" class="empty-intelligence">
                      <Newspaper />
                      <b>暂无今日情报</b>
                      <p>点击右上角“生成今日早报”，系统只会展示带原文链接的真实公开数据；样例、模拟和无出处数据会被拦截。</p>
                    </div>

                    <div v-else class="intelligence-list">
                      <article v-for="(event, index) in intelligenceCards" :key="event.event_key || event.title" class="intelligence-card">
                        <div class="intel-card-top">
                          <span class="intel-rank">#{{ index + 1 }}</span>
                          <div>
                            <h3>{{ event.title }}</h3>
                            <div class="intel-meta">
                              <span>{{ event.category || '综合' }}</span>
                              <span>热度 {{ formatNumber(displayHeatScore(event)) }}</span>
                              <span>来源 {{ event.source_count || event.items?.length || 0 }}</span>
                              <span v-if="event.feedback?.is_favorite" class="favorite-meta"><Heart /> 已收藏</span>
                              <span :class="['cred-pill', credibilityTone(displayCredibilityLevel(event))]">
                                可信度 {{ formatCredibility(event) }}
                              </span>
                            </div>
                          </div>
                        </div>

                        <div class="intel-section">
                          <span class="intel-label">结论</span>
                          <p>{{ event.summary || '暂无摘要，建议打开来源原文继续判断。' }}</p>
                        </div>
                        <div class="intel-section">
                          <span class="intel-label">为什么重要</span>
                          <p>{{ event.business_relevance_reason || event.credibility_reason || '需要结合业务场景继续判断。' }}</p>
                        </div>

                        <div class="evidence-box">
                          <div class="evidence-head">
                            <b><Link2 /> 来源证据</b>
                            <span>{{ evidenceItems(event).length }} 条可追溯线索</span>
                          </div>
                          <div v-if="evidenceItems(event).length" class="evidence-list">
                            <a
                              v-for="item in evidenceItems(event)"
                              :key="item.key"
                              class="evidence-item"
                              :href="item.url || undefined"
                              target="_blank"
                              rel="noreferrer"
                              :aria-disabled="!item.url"
                              @click="!item.url && $event.preventDefault()"
                            >
                              <div>
                                <b>{{ item.title }}</b>
                                <span>{{ item.sourceName }} · {{ item.rankText }}{{ item.hotText }} · {{ item.host || '无链接' }}</span>
                              </div>
                              <ExternalLink v-if="item.url" />
                            </a>
                          </div>
                          <p v-else class="empty-hint">暂无原文链接，这条只能作为低置信线索。</p>
                        </div>

                        <div class="intel-feedback" aria-label="情报反馈操作">
                          <button
                            v-for="action in feedbackActions"
                            :key="action.value"
                            type="button"
                            :class="['feedback-btn', action.tone, feedbackActive(event, action.value) ? 'active' : '']"
                            :disabled="feedbackSavingKey === feedbackButtonKey(event, action.value)"
                            @click="handleEventFeedback(event, action.value)"
                          >
                            <component :is="action.icon" />
                            {{ feedbackActive(event, action.value) ? action.activeText : action.label }}
                          </button>
                        </div>

                        <div class="intel-footer">
                          <span :class="['badge', riskClass(event.risk_level)]">风险 {{ riskLabel(event.risk_level) }}</span>
                          <span class="intel-risk">{{ event.risk_reason || '暂无明显风险' }}</span>
                        </div>
                      </article>
                    </div>

                    <details class="markdown-details">
                      <summary>查看完整 Markdown</summary>
                      <pre class="markdown-box">{{ briefingMarkdown }}</pre>
                    </details>

                    <div class="provider-actions intelligence-bottom-actions">
                      <button class="ghost-btn" type="button" :disabled="!todayBriefing" @click="copyText(briefingMarkdown)"><FileText /> 复制</button>
                      <button class="ghost-btn" type="button" :disabled="!todayBriefing || pushing" @click="handlePush">
                        <Send /> {{ pushing ? '推送中...' : '推送 QQ 机器人' }}
                      </button>
                      <button class="ghost-btn" type="button" :disabled="!todayBriefing" @click="handleIngestLatest"><UploadCloud /> 写入知识库</button>
                    </div>
                  </div>
                </div>

                <div class="side-stack">
                  <div class="card panel" style="padding:20px;">
                    <h3 style="margin:0 0 12px; font-size:15px; font-weight: 700; color: var(--color-text);"><Bot style="width:17px; vertical-align:-3px; margin-right: 4px;" /> 热点分类分布</h3>
                    <div v-for="item in categoryStats" :key="item.name" class="bar-row" style="margin-bottom:10px;">
                      <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
                        <span>{{ item.name }}</span><b>{{ item.count }}</b>
                      </div>
                      <div class="health-bar" style="height:5px; background:var(--surface-subtle); border-radius:999px; overflow:hidden;">
                        <div :style="{ width: item.percent + '%' }" style="height:100%; background-color: var(--color-primary);"></div>
                      </div>
                    </div>
                    <p v-if="!categoryStats.length" class="empty-hint" style="font-size:12px; color:var(--color-muted);">暂无分类数据</p>
                  </div>

                  <div class="card panel" style="padding:20px;">
                    <h3 style="margin:0 0 12px; font-size:15px; font-weight: 700; color: var(--color-text);"><Flame style="width:17px; vertical-align:-3px; margin-right: 4px;" /> 热度前五排行</h3>
                    <div class="event-list">
                      <div v-for="event in topFive" :key="event.event_key || event.title" class="list-item" style="border-bottom:1px solid var(--border-subtle); padding-bottom:8px; margin-bottom:8px; font-size:13px;">
                        <div style="font-weight:700; color:var(--color-text); line-height:1.4;">{{ event.title }}</div>
                        <div style="margin-top:4px; color:var(--color-muted); font-size:12px;">热度 {{ formatNumber(event.heat_score) }} · {{ event.category || '综合' }}</div>
                      </div>
                    </div>
                    <p v-if="!topFive.length" class="empty-hint" style="font-size:12px; color:var(--color-muted);">暂无热点</p>
                  </div>
                </div>
              </div>
            </section>

            <section v-else-if="activePage === 'setup'" class="setup-page-layout">
              <!-- 顶部 Hero 引导卡片 -->
              <div class="card setup-hero-card">
                <div class="setup-hero-main">
                  <div class="setup-hero-badge">
                    <Sparkles class="setup-sparkle-icon" /> 首次引导向导 · 主链路就绪检测
                  </div>
                  <h2 class="setup-hero-title">系统快速就绪与初始化引导</h2>
                  <p class="setup-hero-subtitle">
                    遵循热点捕手端到端主链路：账号安全 → 模型通道 → 数据源采集 → 智能早报 → 知识库与推送。一步直达各对应工作台。
                  </p>
                </div>

                <div class="setup-hero-progress-block">
                  <div class="setup-progress-metric">
                    <div class="setup-percent-display">
                      <span class="setup-percent-num">{{ setupCompletion.percent }}%</span>
                      <span class="setup-percent-label">全链路就绪度</span>
                    </div>
                    <div class="setup-completion-badge" :class="setupCompletion.percent >= 80 ? 'ready' : 'in-progress'">
                      {{ setupCompletion.percent === 100 ? '全部就绪' : (setupCompletion.percent >= 80 ? '核心就绪' : '配置进行中') }}
                    </div>
                  </div>

                  <div class="setup-progress-bar-track">
                    <div class="setup-progress-bar-fill" :style="{ width: setupCompletion.percent + '%' }"></div>
                  </div>

                  <div class="setup-progress-meta">
                    <span>已就绪 <strong>{{ setupSteps.length - setupCompletion.missing.length }}</strong> / {{ setupSteps.length }} 个节点</span>
                    <span v-if="setupCompletion.missing.length > 0" class="setup-pending-tip">
                      剩余 {{ setupCompletion.missing.length }} 项待处理
                    </span>
                    <span v-else class="setup-done-tip">🎉 所有核心节点均已就绪</span>
                  </div>
                </div>
              </div>

              <!-- 中间水平流向步骤指示器 (Stepper Pipeline) -->
              <div class="card setup-pipeline-card">
                <div class="setup-pipeline-title">
                  <Activity style="width: 14px; height: 14px;" /> 链路流转拓扑
                </div>
                <div class="setup-pipeline-steps">
                  <div
                    v-for="(step, index) in setupSteps"
                    :key="`pipeline-${step.key}`"
                    class="setup-pipeline-item"
                    :class="{ 'is-done': step.done, 'is-pending': !step.done }"
                    @click="switchPage(step.page)"
                  >
                    <div class="setup-pipeline-node">
                      <span class="setup-pipeline-num" v-if="!step.done">{{ index + 1 }}</span>
                      <Check v-else class="setup-pipeline-check" />
                    </div>
                    <div class="setup-pipeline-info">
                      <span class="setup-pipeline-name">{{ step.title }}</span>
                      <span class="setup-pipeline-state">{{ step.done ? '已就绪' : '待处理' }}</span>
                    </div>
                    <div v-if="index < setupSteps.length - 1" class="setup-pipeline-connector"></div>
                  </div>
                </div>
              </div>

              <!-- 精致卡片网格 -->
              <div class="setup-cards-grid">
                <div
                  v-for="(step, index) in setupSteps"
                  :key="step.key"
                  class="card setup-card"
                  :class="{ 'is-done': step.done, 'is-pending': !step.done }"
                >
                  <div class="setup-card-top">
                    <div class="setup-card-icon-wrap" :class="{ 'done-icon': step.done }">
                      <component :is="step.icon" class="setup-card-icon" />
                    </div>
                    <span class="setup-card-index">STEP 0{{ index + 1 }}</span>
                    <div class="setup-card-status">
                      <span v-if="step.done" class="setup-status-tag done">
                        <Check style="width: 11px; height: 11px;" /> 已完成
                      </span>
                      <span v-else class="setup-status-tag pending">
                        <Clock3 style="width: 11px; height: 11px;" /> 待处理
                      </span>
                    </div>
                  </div>

                  <div class="setup-card-main">
                    <h3 class="setup-card-title">{{ step.title }}</h3>
                    <p class="setup-card-desc">{{ step.desc }}</p>
                  </div>

                  <div class="setup-card-action-bar">
                    <button
                      type="button"
                      :class="step.done ? 'ghost-btn setup-action-btn' : 'primary-btn setup-action-btn'"
                      @click="switchPage(step.page)"
                    >
                      {{ step.action }}
                      <span class="action-arrow">→</span>
                    </button>
                  </div>
                </div>
              </div>

              <!-- 底部操作栏 -->
              <div class="card setup-footer-card">
                <div class="setup-footer-tip">
                  <span class="tip-icon">💡</span>
                  <span>所有配置变更将即时生效并持久化。主链路就绪后，可随时在「自动任务」中启用无人值守定时调度。</span>
                </div>
                <div class="setup-footer-btns">
                  <button class="ghost-btn" type="button" @click="switchPage('dashboard')">
                    返回今日情报
                  </button>
                  <button class="primary-btn pulse-on-ready" type="button" :disabled="generating" @click="handleGenerate">
                    <Sparkles style="width: 15px; height: 15px;" /> {{ generating ? '生成中...' : '生成今日早报' }}
                  </button>
                </div>
              </div>
            </section>

            <!-- Data Board Page -->
            <DataBoardPage v-else-if="activePage === 'dataBoard'" ref="dataBoardPageRef" @message="setMessage" @error="setError" @set-loading="loading = $event" />

            <!-- Feedback Records Page -->
            <FeedbackRecordsPage v-else-if="activePage === 'feedbackRecords'" ref="feedbackRecordsPageRef" @message="setMessage" @error="setError" @set-loading="loading = $event" />

            <!-- Events Page -->
            <EventTable v-else-if="activePage === 'events'" v-model:categoryFilter="eventFilters.category" v-model:riskFilter="eventFilters.risk_level" :events="events" :categories="eventCategories" @update:categoryFilter="loadEventsPage" @update:riskFilter="loadEventsPage" />

            <!-- History Page -->
            <section v-else-if="activePage === 'history'" class="history-layout">
              <div class="card panel history-sidebar-panel">
                <div class="panel-head small">
                  <div class="history-head-title">
                    <h2>历史早报</h2>
                    <span class="count-badge">{{ filteredHistory.length }} 份</span>
                  </div>
                  <button class="ghost-btn small-btn" type="button" :disabled="loading" @click="loadHistoryPage">
                    <RefreshCw :class="{ spinning: loading }" style="width: 13px; height: 13px;" /> 刷新
                  </button>
                </div>
                <div class="history-filter-wrap">
                  <Search class="history-search-icon" />
                  <input
                    v-model="historySearchQuery"
                    type="text"
                    placeholder="搜索日期或关键词..."
                    class="history-search-input"
                  />
                  <button v-if="historySearchQuery" class="clear-search-btn" type="button" @click="historySearchQuery = ''">✕</button>
                </div>
                <div class="history-list">
                  <button
                    v-for="item in filteredHistory"
                    :key="item.briefing_date"
                    type="button"
                    :class="['history-item', { active: selectedHistoryDate === item.briefing_date }]"
                    @click="selectHistory(item.briefing_date)"
                  >
                    <div class="history-item-body">
                      <div class="history-item-header">
                        <span class="history-item-date">{{ item.briefing_date }}</span>
                        <span :class="['badge', item.status === 'SUCCESS' || item.status === 'READY' ? 'low' : 'medium']">
                          {{ statusLabel(item.status) }}
                        </span>
                      </div>
                      <p class="history-item-summary">{{ cleanHistorySummary(item.summary || item.title || '') }}</p>
                    </div>
                  </button>
                  <p v-if="!filteredHistory.length" class="empty-hint">
                    {{ historySearchQuery ? '未找到匹配的早报' : '暂无历史早报' }}
                  </p>
                </div>
              </div>
              <div class="card panel history-content-panel">
                <div class="panel-head">
                  <div class="history-title-group">
                    <h2>{{ selectedBriefing?.title || '早报详情' }}</h2>
                    <span class="history-date-chip">{{ selectedBriefing?.briefing_date || '-' }}</span>
                  </div>
                  <div class="top-actions">
                    <div class="history-mode-switch" role="group" aria-label="视图模式切换">
                      <button
                        type="button"
                        :class="['mode-btn', { active: historyViewMode === 'rendered' }]"
                        @click="historyViewMode = 'rendered'"
                      >
                        <BookOpen style="width: 13px; height: 13px;" /> 排版阅读
                      </button>
                      <button
                        type="button"
                        :class="['mode-btn', { active: historyViewMode === 'source' }]"
                        @click="historyViewMode = 'source'"
                      >
                        <Code style="width: 13px; height: 13px;" /> 源码
                      </button>
                    </div>
                    <button class="ghost-btn small-btn" type="button" :disabled="!selectedHistoryDate" @click="handleRegenerateHistory">
                      <RefreshCw style="width: 13px; height: 13px;" /> 重生成
                    </button>
                    <button class="primary-btn small-btn" type="button" :disabled="!selectedBriefing" @click="copyText(selectedBriefing?.markdown || '')">
                      <FileText style="width: 13px; height: 13px;" /> 复制
                    </button>
                  </div>
                </div>
                <div class="history-content-body">
                  <div v-if="historyViewMode === 'rendered'" class="history-rendered-view">
                    <div
                      v-if="selectedBriefing?.markdown"
                      class="briefing-doc-reader"
                      v-html="renderBriefingHtml(selectedBriefing.markdown)"
                    />
                    <div v-else class="empty-hint-card">
                      <p>请在左侧列表中点击选择要查看的历史早报。</p>
                    </div>
                  </div>
                  <div v-else class="history-markdown-container">
                    <pre class="history-markdown">{{ selectedBriefing?.markdown || '请在左侧列表中点击选择要查看的历史早报。' }}</pre>
                  </div>
                </div>
              </div>
            </section>

            <!-- Knowledge Base RAG -->
            <KnowledgePage v-else-if="activePage === 'knowledge'" ref="knowledgePageRef" @message="setMessage" @error="setError" @set-loading="loading = $event" />

            <!-- Knowledge QA Assistant -->
            <KnowledgeQAPage v-else-if="activePage === 'knowledgeQa'" ref="knowledgeQaPageRef" @message="setMessage" @error="setError" @set-loading="loading = $event" />

            <!-- Collection Source Status Page (Simplified full-width list) -->
            <section v-else-if="activePage === 'sourceHealth'">
              <div class="card panel platform-fetch-panel">
                <div class="panel-head">
                  <div>
                    <h2>系统关注热点即时抓取</h2>
                    <p>GitHub · Hugging Face · DEV Community</p>
                  </div>
                  <div class="top-actions platform-fetch-actions">
                    <button class="primary-btn" type="button" :disabled="platformFetching" @click="handleFetchPlatforms(['github', 'huggingface', 'devto'])">
                      <RefreshCw :class="{ spinning: platformFetching }" /> {{ platformFetching ? '抓取中...' : '抓取平台系统热点' }}
                    </button>
                    <button class="ghost-btn" type="button" :disabled="platformFetching" @click="handleFetchPlatforms(['github'])">
                      <RefreshCw /> GitHub
                    </button>
                    <button class="ghost-btn" type="button" :disabled="platformFetching" @click="handleFetchPlatforms(['huggingface'])">
                      <RefreshCw /> Hugging Face
                    </button>
                  </div>
                </div>

                <div v-if="platformHotspots" class="platform-result-grid">
                  <div v-for="source in Object.values(platformHotspots.sources)" :key="source.code" class="platform-result-card">
                    <div class="platform-result-head">
                      <div>
                        <h3>{{ source.name }}</h3>
                        <p>{{ source.code }} · {{ source.count }} 条 · limit {{ platformHotspots.limit }}</p>
                      </div>
                      <span :class="['badge', source.status === 'SUCCESS' ? 'low' : 'high']">{{ statusLabel(source.status) }}</span>
                    </div>
                    <div v-if="source.items.length" class="platform-hot-list">
                      <a
                        v-for="item in source.items.slice(0, 10)"
                        :key="`${source.code}-${item.source_item_id || item.rank}`"
                        class="platform-hot-item"
                        :href="item.url || '#'"
                        target="_blank"
                        rel="noreferrer"
                      >
                        <span class="platform-rank">{{ item.rank }}</span>
                        <span class="platform-title-wrap">
                          <span class="platform-title">{{ item.title }}</span>
                          <small>{{ platformItemCategory(item) }}</small>
                        </span>
                        <b>{{ item.raw_hot_score || '-' }}</b>
                      </a>
                    </div>
                    <p v-else class="empty-hint">{{ source.error || '本次没有抓到数据' }}</p>
                  </div>
                </div>
                <p v-else class="empty-hint">点击上方按钮即可即时抓取系统关注方向的真实公开数据，不会污染每日早报。</p>
              </div>

              <div class="card panel">
                <div class="panel-head">
                  <div>
                    <h2>采集源状态</h2>
                    <p>实时执行各 connector 的公开采集，不写库、不污染早报；同时保留历史成功率。</p>
                    <p v-if="sourceHealth?.live_probe?.enabled" class="mini-note">
                      最近实时探测：{{ formatDateTime(sourceHealth.live_probe.checked_at) }}，
                      成功 {{ sourceHealth.live_probe.success || 0 }}，
                      失败 {{ sourceHealth.live_probe.failed || 0 }}，
                      拦截样例 {{ sourceHealth.live_probe.dropped_fallback_count || 0 }}，
                      拦截无出处 {{ sourceHealth.live_probe.dropped_no_evidence_count || 0 }}。
                    </p>
                  </div>
                  <div class="top-actions">
                    <button class="ghost-btn" type="button" :disabled="loading" @click="loadSourceHealthPage">
                      <RefreshCw :class="{ spinning: loading }" /> 实时重测全部源
                    </button>
                  </div>
                </div>
                <div class="table-wrap">
                  <table class="data-table source-table">
                    <thead><tr><th>源</th><th>实时状态</th><th>本次真实</th><th>耗时</th><th>历史成功率</th><th>历史真实</th><th>最近结果</th><th>操作</th></tr></thead>
                    <tbody>
                      <tr v-for="item in sourceHealth?.items || []" :key="item.code" @click="openSourceDetail(item)" style="cursor: pointer;">
                        <td class="title-cell"><b>{{ item.name }}</b><div class="muted-text">{{ item.code }}</div></td>
                        <td>
                          <span :class="['badge', healthClass(item.health_level)]">{{ sourceLiveStatus(item) }}</span>
                          <div class="muted-text">{{ formatDateTime(item.live_checked_at) }}</div>
                        </td>
                        <td>
                          <b>{{ item.live_probe?.real_count ?? '-' }}</b>
                          <div class="muted-text">预览 {{ item.live_probe?.preview_count ?? 0 }} 条 · 拦截无出处 {{ item.live_probe?.dropped_no_evidence_count ?? 0 }}</div>
                        </td>
                        <td>{{ formatMs(item.live_latency_ms) }}</td>
                        <td>{{ formatPercent(item.success_rate) }}<div class="health-bar"><div :style="{ width: Math.min(100, Math.round(item.success_rate || 0)) + '%' }"></div></div></td>
                        <td>{{ item.real_items }}</td>
                        <td class="error-cell">{{ sourceLiveMessage(item) }}</td>
                        <td><button class="ghost-btn small-btn" type="button" @click.stop="openSourceDetail(item)">详情</button></td>
                      </tr>
                      <tr v-if="!(sourceHealth?.items || []).length"><td colspan="8" class="empty-cell">暂无数据</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <!-- System Logs Page -->
            <SystemLogPage v-else-if="activePage === 'systemLogs'" ref="systemLogPageRef" @message="setMessage" @error="setError" @set-loading="loading = $event" />

            <!-- Profile Page -->
            <ProfilePage v-else-if="activePage === 'profile'" :profile="currentUser" @logout="handleLogout" @refresh="refreshProfile" @message="setMessage" @error="setError" @set-loading="loading = $event" />

            <!-- Ingest Runs Page -->
            <RunTable v-else-if="activePage === 'runs'" :runs="runs" :ingestRuns="ingestRuns" />

            <!-- Scheduler Timing Page -->
            <section v-else-if="activePage === 'scheduler'" class="scheduler-split-layout">
              <div class="scheduler-config-col">
                <div class="card panel scheduler-panel">
                  <div class="panel-head">
                    <div>
                      <h2>自动任务配置</h2>
                      <p>服务器无人值守自动抓取、分析热点并生成每日早报。</p>
                    </div>
                    <span :class="['badge', schedulerStatus?.scheduler_running ? 'low' : 'medium']">
                      {{ statusLabel(schedulerStatus?.scheduler_running ? 'RUNNING' : 'STOPPED') }}
                    </span>
                  </div>

                  <div class="scheduler-section-block">
                    <h3 class="section-subtitle">
                      <Clock3 style="width: 15px; height: 15px;" /> 定时触发规则
                    </h3>
                    <div class="scheduler-switch-row">
                      <div class="switch-meta">
                        <b>启用定时调度</b>
                        <span>开启后，后台引擎将在每天指定时间自动执行热点任务</span>
                      </div>
                      <label class="toggle-switch">
                        <input v-model="schedulerForm.enabled" type="checkbox" />
                        <span class="slider round"></span>
                      </label>
                    </div>

                    <div class="compact-grid">
                      <label class="form-item">
                        <span>触发小时 (0-23)</span>
                        <input v-model.number="schedulerForm.hour" type="number" min="0" max="23" />
                      </label>
                      <label class="form-item">
                        <span>触发分钟 (0-59)</span>
                        <input v-model.number="schedulerForm.minute" type="number" min="0" max="59" />
                      </label>
                      <label class="form-item" style="grid-column: 1 / -1;">
                        <span>标准时区</span>
                        <input v-model="schedulerForm.timezone" placeholder="Asia/Shanghai" />
                      </label>
                    </div>
                  </div>

                  <div class="scheduler-section-block">
                    <h3 class="section-subtitle">
                      <ShieldCheck style="width: 15px; height: 15px;" /> 并发与任务安全锁
                    </h3>
                    <div class="scheduler-switch-row">
                      <div class="switch-meta">
                        <b>允许同日重跑</b>
                        <span>若当天已有早报，是否允许定时器再次执行覆盖</span>
                      </div>
                      <label class="toggle-switch">
                        <input v-model="schedulerForm.allow_rerun_same_day" type="checkbox" />
                        <span class="slider round"></span>
                      </label>
                    </div>

                    <div class="compact-grid">
                      <label class="form-item">
                        <span>失败重试次数</span>
                        <input v-model.number="schedulerForm.retry_times" type="number" min="0" />
                      </label>
                      <label class="form-item">
                        <span>重试间隔 (秒)</span>
                        <input v-model.number="schedulerForm.retry_delay_seconds" type="number" min="1" />
                      </label>
                      <label class="form-item" style="grid-column: 1 / -1;">
                        <span>分布式任务锁 TTL (分钟)</span>
                        <input v-model.number="schedulerForm.lock_ttl_minutes" type="number" min="1" />
                      </label>
                    </div>
                  </div>

                  <div class="provider-actions" style="margin-top: 18px; padding: 14px 20px; border-top: 1px solid var(--border-subtle);">
                    <button class="ghost-btn" type="button" @click="handleRunScheduler">
                      <Zap style="width: 14px; height: 14px;" /> 立即执行一次
                    </button>
                    <button class="primary-btn" type="button" @click="handleSaveScheduler">
                      保存配置
                    </button>
                  </div>
                </div>
              </div>

              <div class="scheduler-monitor-col">
                <div class="card panel scheduler-monitor-panel">
                  <div class="panel-head small">
                    <div class="monitor-head">
                      <span :class="['pulse-dot', schedulerStatus?.scheduler_running ? 'online' : 'offline']"></span>
                      <h2>调度器实时监控</h2>
                    </div>
                  </div>

                  <div class="scheduler-monitor-body">
                    <div class="monitor-hero-card">
                      <span class="hero-label">下次计划触发时间</span>
                      <div class="hero-time">
                        {{ schedulerStatus?.next_run_time ? formatDateTime(schedulerStatus.next_run_time) : '暂无自动任务' }}
                      </div>
                      <span class="hero-hint">
                        {{ schedulerStatus?.scheduler_running ? '调度器正在后台稳定驻留' : '调度器目前处于停止状态' }}
                      </span>
                    </div>

                    <div class="monitor-info-list">
                      <div class="monitor-info-row">
                        <span>任务 Job ID</span>
                        <b class="font-mono">{{ schedulerStatus?.job_id || 'daily_hotspot_briefing' }}</b>
                      </div>
                      <div class="monitor-info-row">
                        <span>注册状态</span>
                        <span :class="['badge', schedulerStatus?.job_exists ? 'low' : 'medium']">
                          {{ schedulerStatus?.job_exists ? '已注册' : '未注册' }}
                        </span>
                      </div>
                      <div class="monitor-info-row">
                        <span>今日已跑状态</span>
                        <span :class="['badge', schedulerStatus?.today_has_briefing ? 'low' : 'medium']">
                          {{ schedulerStatus?.today_has_briefing ? '今日已生成' : '今日未生成' }}
                        </span>
                      </div>
                      <div class="monitor-info-row">
                        <span>执行中实例</span>
                        <b>{{ schedulerStatus?.running_count || 0 }} 个</b>
                      </div>
                      <div class="monitor-info-row">
                        <span>分布式任务锁</span>
                        <b class="font-mono">{{ schedulerStatus?.lock_key || '未锁定' }}</b>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <!-- Model Stats Page -->
            <section v-else-if="activePage === 'modelStats'">
              <div class="stat-grid model-stat-grid">
                <div class="card stat-card"><p class="stat-label">总调用</p><p class="stat-value">{{ modelStats?.total_calls ?? 0 }}</p></div>
                <div class="card stat-card"><p class="stat-label">成功率</p><p class="stat-value">{{ formatPercent(modelStats?.success_rate || 0) }}</p></div>
                <div class="card stat-card"><p class="stat-label">平均延迟</p><p class="stat-value">{{ formatDuration(modelStats?.avg_latency_ms) }}</p></div>
                <div class="card stat-card"><p class="stat-label">Token</p><p class="stat-value">{{ modelStats?.total_tokens ?? 0 }}</p></div>
                <div class="card stat-card"><p class="stat-label">预估成本</p><p class="stat-value">{{ formatUsd(modelStats?.total_estimated_cost) }}</p></div>
              </div>
              <div class="card panel" style="margin-top: 16px;">
                <div class="panel-head small"><h2>历史调用趋势</h2></div>
                <div class="table-wrap">
                  <table class="data-table">
                    <thead><tr><th>时间</th><th>状态</th><th>通道</th><th>模型</th><th>耗时</th><th>Token</th><th>预估成本</th><th>错误信息</th></tr></thead>
                    <tbody>
                      <tr v-for="call in modelStats?.recent_calls || []" :key="call.id">
                        <td>{{ formatDateTime(call.created_at) }}</td>
                        <td><span :class="['badge', statusBadgeClass(call.status)]">{{ statusLabel(call.status) }}</span></td>
                        <td>{{ call.provider_code }}</td>
                        <td>{{ call.model }}</td>
                        <td>{{ formatDuration(call.latency_ms) }}</td>
                        <td>{{ call.total_tokens || 0 }}</td>
                        <td>{{ formatUsd(call.estimated_cost) }}</td>
                        <td class="error-cell">{{ call.error_message || '-' }}</td>
                      </tr>
                      <tr v-if="!(modelStats?.recent_calls || []).length"><td colspan="8" class="empty-cell">暂无数据</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <!-- QQ Push Config Page -->
            <section v-else-if="activePage === 'pushConfig'" class="push-split-layout">
              <form class="card panel push-config-panel" autocomplete="off" @submit.prevent="handleSavePush">
                <div class="panel-head">
                  <div>
                    <h2>QQ 机器人推送配置</h2>
                    <p>基于 OneBot v11 协议，每日早报生成后自动推送到指定群或好友。</p>
                  </div>
                </div>
                <div class="push-form-body">
                  <div class="scheduler-switch-row" style="margin-bottom: 16px;">
                    <div class="switch-meta">
                      <b>启用 OneBot 自动推送</b>
                      <span>开启后，早报生成成功时自动发送卡片消息</span>
                    </div>
                    <label class="toggle-switch">
                      <input v-model="pushForm.enabled" type="checkbox" aria-label="启用 OneBot 自动推送" />
                      <span class="slider round"></span>
                    </label>
                  </div>

                  <div class="form-grid">
                    <label class="form-item wide">
                      <span>OneBot HTTP API 地址</span>
                      <input v-model="pushForm.onebot_api_base" placeholder="http://127.0.0.1:3000" />
                    </label>

                    <label class="form-item wide">
                      <span>接收推送类型</span>
                      <div class="radio-pill-group">
                        <label :class="['radio-pill', { active: pushForm.target_type === 'private' }]">
                          <input v-model="pushForm.target_type" type="radio" value="private" style="display: none;" />
                          私聊好友
                        </label>
                        <label :class="['radio-pill', { active: pushForm.target_type === 'group' }]">
                          <input v-model="pushForm.target_type" type="radio" value="group" style="display: none;" />
                          群聊消息
                        </label>
                      </div>
                    </label>

                    <label v-if="pushForm.target_type === 'private'" class="form-item wide">
                      <span>好友 QQ 号码</span>
                      <input v-model="pushForm.user_id" placeholder="输入接收推送的个人 QQ 号" />
                    </label>
                    <label v-else class="form-item wide">
                      <span>群号 QQ</span>
                      <input v-model="pushForm.group_id" placeholder="输入接收推送的 QQ 群号" />
                    </label>

                    <label class="form-item wide">
                      <span>Access Token</span>
                      <div class="password-input-wrap">
                        <input
                          v-model="pushForm.access_token"
                          :type="showPushToken ? 'text' : 'password'"
                          autocomplete="new-password"
                          :spellcheck="false"
                          placeholder="如客户端配置了 token 请填写，无则留空"
                        />
                        <button class="toggle-pwd-btn" type="button" @click="showPushToken = !showPushToken">
                          <Eye v-if="!showPushToken" style="width: 14px; height: 14px;" />
                          <EyeOff v-else style="width: 14px; height: 14px;" />
                        </button>
                      </div>
                    </label>
                  </div>

                  <div class="provider-actions" style="margin-top: 20px; padding-top: 14px; border-top: 1px solid var(--border-subtle);">
                    <button class="ghost-btn" type="button" @click="handleTestPush">
                      <Send style="width: 13px; height: 13px;" /> 测试连通性
                    </button>
                    <button class="primary-btn" type="submit">保存推送配置</button>
                  </div>
                </div>
              </form>

              <!-- QQ Message Simulator -->
              <div class="card panel qq-simulator-panel">
                <div class="panel-head small">
                  <div class="simulator-head">
                    <MessageSquare style="width: 15px; height: 15px; color: var(--color-primary);" />
                    <h2>QQ 消息推送实时效果模拟</h2>
                  </div>
                  <span class="badge low">{{ pushForm.target_type === 'group' ? '群聊模式' : '好友私聊' }}</span>
                </div>
                <div class="qq-chat-window">
                  <div class="qq-chat-header">
                    <div class="qq-avatar bot-avatar">🤖</div>
                    <div class="qq-peer-info">
                      <b>{{ pushForm.target_type === 'group' ? `热点推送群 (${pushForm.group_id || '987654321'})` : `热点捕手 Agent (${pushForm.user_id || '12345678'})` }}</b>
                      <span>OneBot v11 · 在线</span>
                    </div>
                  </div>
                  <div class="qq-chat-body">
                    <div class="qq-msg-bubble">
                      <div class="qq-msg-time">{{ dayjs().format('HH:mm') }}</div>
                      <div class="qq-card-preview">
                        <div class="qq-card-title">📰 今日热点早报汇总</div>
                        <div class="qq-card-date">{{ dayjs().format('YYYY-MM-DD') }} · 自动化日报</div>
                        <div class="qq-card-body">
                          <p><b>【核心热点速递】</b></p>
                          <p>1. AI 大模型架构全新演进，多模态推理能力显著突破</p>
                          <p>2. 开源生态最新动态：自动化智能体框架更新</p>
                          <p>3. 行业风险预警：知识库检索命中相关技术专利变动</p>
                        </div>
                        <div class="qq-card-foot">
                          <span>出处真实可溯源 · 热点捕手 Agent 自动推送</span>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div class="qq-chat-footer">
                    <span class="muted-text">提示：实际推送内容将包含完整早报文本或图文卡片</span>
                  </div>
                </div>
              </div>
            </section>

            <!-- Models Providers Setup Page -->
            <section v-else-if="activePage === 'models'" class="model-grid">
              <div v-for="item in providers" :key="item.id" class="card model-card-simple">
                <div class="provider-head-simple">
                  <div class="provider-info">
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <b>{{ item.name }}</b>
                      <span class="count-badge">{{ providerBrandTag(item.code, item.name).label }}</span>
                    </div>
                    <span class="provider-code-subtitle">{{ item.code }}</span>
                  </div>
                  <span :class="['badge', item.enabled ? 'low' : 'medium']">{{ item.enabled ? '已启用' : '已停用' }}</span>
                </div>
                <div class="provider-details-simple">
                  <div class="detail-row"><span class="label">当前模型</span><span class="value">{{ item.model || '自动指定' }}</span></div>
                  <div class="detail-row"><span class="label">通道优先级</span><span class="value">{{ item.priority }}</span></div>
                  <div class="detail-row"><span class="label">百万 Token 单价</span><span class="value">{{ providerCostLabel(item) }}</span></div>
                </div>
                <div class="provider-actions" style="margin-top: 12px; justify-content: flex-end;">
                  <button :class="['ghost-btn small-btn', item.enabled ? 'warning-btn' : 'success-btn']" type="button" @click="toggleProviderEnabled(item)">
                    {{ item.enabled ? '禁用' : '启用' }}
                  </button>
                  <button class="ghost-btn small-btn" type="button" @click="openEditModal(item)">编辑通道</button>
                  <button class="ghost-btn small-btn error-btn" type="button" @click="handleDeleteProvider(item)">删除</button>
                </div>
              </div>
              <button class="card model-card-simple add-card" type="button" aria-label="添加模型通道" @click="openEditModal(defaultProvider())">
                <Plus style="width: 26px; height: 26px;" />
                <span style="font-weight: 600; font-size: 13px;">添加模型通道</span>
              </button>
            </section>
          </div>
        </Transition>
      </section>
    </main>
  </div>

  <div v-else class="auth-loading-screen">
    <RefreshCw class="spinning" />
    <span>正在检查登录状态...</span>
  </div>

  <!-- Loading Overlay -->
  <div v-if="loading && isAuthenticated" class="global-loading">
    <RefreshCw class="spinning" />
    <span>加载中...</span>
  </div>

  <GenerateBriefingModal
    :visible="isAuthenticated && generating"
    :steps="generatingSteps"
    :currentStep="generatingStep"
    :autoIngest="generatingAutoIngest"
    :ingestStatus="generatingIngestStatus"
    :ingestMessage="generatingIngestMessage"
    :task="generatingTask"
  />

  <Teleport to="body">
    <TransitionGroup name="toast-fade" tag="div" class="chrome-toast-container" aria-live="polite" aria-relevant="additions">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        :class="['chrome-toast', toast.type]"
        :role="toast.type === 'error' ? 'alert' : 'status'"
      >
        <span class="toast-text">{{ toast.message }}</span>
        <button class="toast-close" type="button" aria-label="关闭提示" @click="removeToast(toast.id)"><X /></button>
      </div>
    </TransitionGroup>
  </Teleport>

  <!-- Model Edit Modal -->
  <Transition name="fade-slide">
    <div v-if="isEditModalOpen && editingProvider" class="chrome-modal-overlay" @click.self="closeEditModal">
      <form class="chrome-dialog edit-provider-modal" autocomplete="off" @submit.prevent="handleSaveEditingProvider">
        <div class="chrome-dialog-head">
          <div class="modal-title-group">
            <div class="modal-badge-icon">
              <Cpu class="icon-svg" />
            </div>
            <div class="modal-title-text">
              <h3>配置模型通道</h3>
              <span class="modal-subtitle font-mono">{{ editingProvider.name || '新通道' }} ({{ editingProvider.code || 'custom' }})</span>
            </div>
          </div>
          <button class="close-btn" type="button" aria-label="关闭模型配置" @click="closeEditModal"><X /></button>
        </div>

        <div class="chrome-dialog-body edit-provider-body">
          <!-- Section 1: 基础连接与认证 -->
          <div class="modal-section">
            <div class="section-title-row">
              <span class="section-title">基础接口与凭据</span>
              <div class="section-switches">
                <label class="toggle-pill" :class="{ checked: editingProvider.enabled }">
                  <input v-model="editingProvider.enabled" type="checkbox" />
                  <span class="pill-dot"></span>
                  <span>启用该通道</span>
                </label>
                <label class="toggle-pill" :class="{ checked: editingProvider.requires_api_key }">
                  <input v-model="editingProvider.requires_api_key" type="checkbox" />
                  <span class="pill-dot"></span>
                  <span>需要 API Key</span>
                </label>
              </div>
            </div>

            <div class="modal-form-grid-2">
              <div class="modal-form-item">
                <label class="item-label" for="provider-code">Code（唯一标识）</label>
                <input
                  id="provider-code"
                  v-model="editingProvider.code"
                  :disabled="Boolean(editingProvider.id)"
                  placeholder="如: openai-gpt4"
                  class="modal-input font-mono"
                  required
                />
                <span class="item-hint">通道底层唯一编码，创建后不可更改</span>
              </div>

              <div class="modal-form-item">
                <label class="item-label" for="provider-name">通道名称</label>
                <input
                  id="provider-name"
                  v-model="editingProvider.name"
                  placeholder="填写模型通道名称"
                  class="modal-input"
                  required
                />
                <span class="item-hint">界面展示与调度日志使用的通道友好名</span>
              </div>
            </div>

            <div class="modal-form-item full-width">
              <label class="item-label" for="provider-url">Base URL (接口地址)</label>
              <input
                id="provider-url"
                v-model="editingProvider.base_url"
                placeholder="https://api.openai.com/v1"
                class="modal-input font-mono"
                required
              />
              <span class="item-hint">支持任何兼容 OpenAI v1 规范的接口端点</span>
            </div>

            <div v-if="editingProvider.requires_api_key" class="modal-form-item full-width">
              <label class="item-label" for="provider-api-key">API Key 凭据</label>
              <div class="input-with-action">
                <input
                  id="provider-api-key"
                  v-model="editingProvider.api_key"
                  :type="showApiKey ? 'text' : 'password'"
                  autocomplete="new-password"
                  :spellcheck="false"
                  :placeholder="editingProvider.api_key_masked || '输入 API Key（留空保持原配置不变）'"
                  class="modal-input font-mono"
                />
                <button
                  class="action-btn-inside"
                  type="button"
                  :title="showApiKey ? '隐藏密钥' : '显示密钥'"
                  @click="showApiKey = !showApiKey"
                >
                  <component :is="showApiKey ? EyeOff : Eye" class="btn-icon" />
                </button>
              </div>
              <span class="item-hint">
                {{ editingProvider.api_key_masked ? `当前已配置：${editingProvider.api_key_masked}（如不修改请留空）` : '请输入供应商分配的 Bearer Token / API Key' }}
              </span>
            </div>
          </div>

          <!-- Section 2: 模型绑定与发现 -->
          <div class="modal-section">
            <div class="section-title-row">
              <span class="section-title">模型指定与在线探测</span>
              <button
                class="ghost-btn fetch-btn"
                type="button"
                :disabled="isFetchingModels"
                @click="onFetchModelsClick(editingProvider)"
              >
                <RefreshCw class="btn-icon" :class="{ spinning: isFetchingModels }" />
                {{ isFetchingModels ? '获取中...' : '获取在线模型列表' }}
              </button>
            </div>

            <div class="modal-form-item full-width">
              <label class="item-label" for="provider-model">当前生效模型 (Model)</label>
              <div class="model-input-combo">
                <input
                  id="provider-model"
                  v-model="editingProvider.model"
                  placeholder="填写服务支持的模型标识"
                  class="modal-input font-mono"
                  required
                />
                <select
                  v-if="providerOptions(editingProvider).length"
                  class="model-picker-select font-mono"
                  @change="onModelSelectChange($event)"
                >
                  <option value="">-- 从已获取的 {{ providerOptions(editingProvider).length }} 个模型中快速选用 --</option>
                  <option
                    v-for="opt in providerOptions(editingProvider)"
                    :key="opt"
                    :value="opt"
                    :selected="opt === editingProvider.model"
                  >
                    {{ opt }}
                  </option>
                </select>
              </div>
              <span class="item-hint">可以直接手动键入，或点击右上角“获取在线模型列表”后从下拉列表中直接选用</span>
            </div>

            <!-- Quick chips if options available -->
            <div v-if="providerOptions(editingProvider).length" class="quick-models-row">
              <span class="quick-label">快捷选择:</span>
              <div class="quick-chips">
                <button
                  v-for="opt in providerOptions(editingProvider).slice(0, 5)"
                  :key="opt"
                  type="button"
                  class="model-chip font-mono"
                  :class="{ active: editingProvider.model === opt }"
                  @click="editingProvider.model = opt"
                >
                  {{ opt }}
                </button>
              </div>
            </div>
          </div>

          <!-- Section 3: 推理控制与调度参数 -->
          <div class="modal-section">
            <div class="section-title-row">
              <span class="section-title">推理控制与调度参数</span>
            </div>

            <div class="modal-form-grid-4">
              <div class="modal-form-item">
                <label class="item-label">通道优先级</label>
                <input
                  v-model.number="editingProvider.priority"
                  type="number"
                  min="1"
                  class="modal-input"
                  required
                />
                <span class="item-hint">数字越小越优先调度</span>
              </div>

              <div class="modal-form-item">
                <label class="item-label">网络超时 (秒)</label>
                <input
                  v-model.number="editingProvider.timeout_seconds"
                  type="number"
                  min="5"
                  class="modal-input"
                  required
                />
                <span class="item-hint">请求超时时长 (秒)</span>
              </div>

              <div class="modal-form-item">
                <label class="item-label">Max Tokens</label>
                <input
                  v-model.number="editingProvider.max_tokens"
                  type="number"
                  min="100"
                  class="modal-input"
                  required
                />
                <span class="item-hint">单次最大生成上限</span>
              </div>

              <div class="modal-form-item">
                <label class="item-label">Temperature</label>
                <input
                  v-model.number="editingProvider.temperature"
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                  class="modal-input"
                  required
                />
                <span class="item-hint">随机度 0.0 ~ 2.0</span>
              </div>
            </div>
          </div>

          <!-- Section 4: 计费规格与备注 -->
          <div class="modal-section">
            <div class="section-title-row">
              <span class="section-title">计费成本与说明</span>
            </div>

            <div class="modal-form-grid-2">
              <div class="modal-form-item">
                <label class="item-label" for="provider-input-price">输入单价 (USD / 百万 Token)</label>
                <input
                  id="provider-input-price"
                  v-model.number="editingProvider.input_cost_per_million"
                  type="number"
                  min="0"
                  step="0.000001"
                  class="modal-input font-mono"
                />
                <span class="item-hint">如 $0.15 / 1M Tokens 填 0.15</span>
              </div>

              <div class="modal-form-item">
                <label class="item-label" for="provider-output-price">输出单价 (USD / 百万 Token)</label>
                <input
                  id="provider-output-price"
                  v-model.number="editingProvider.output_cost_per_million"
                  type="number"
                  min="0"
                  step="0.000001"
                  class="modal-input font-mono"
                />
                <span class="item-hint">如 $0.60 / 1M Tokens 填 0.6</span>
              </div>
            </div>

            <div class="modal-form-item full-width" style="margin-top: 6px;">
              <label class="item-label">通道备注说明</label>
              <textarea
                v-model="editingProvider.note"
                rows="2"
                placeholder="备注该通道的用途、配额限速或特殊调用说明..."
                class="modal-textarea"
              ></textarea>
            </div>
          </div>
        </div>

        <div class="chrome-dialog-foot modal-foot-custom">
          <button
            class="ghost-btn test-conn-btn"
            type="button"
            :disabled="isTestingProvider"
            @click="onTestProviderClick(editingProvider)"
          >
            <Wifi class="btn-icon" :class="{ spinning: isTestingProvider }" />
            {{ isTestingProvider ? '正在测试连通性...' : '测试连通性' }}
          </button>
          <div class="foot-spacer"></div>
          <button class="ghost-btn cancel-btn" type="button" @click="closeEditModal">取消</button>
          <button class="primary-btn save-btn" type="submit">
            <Check class="btn-icon" /> 保存配置
          </button>
        </div>
      </form>
    </div>
  </Transition>

  <!-- Collection Source Detail Modal (Popup) -->
  <Transition name="fade-slide">
    <div v-if="isSourceDetailOpen && selectedSource" class="chrome-modal-overlay" @click.self="closeSourceDetail">
      <div class="chrome-dialog source-detail-modal">
        <div class="chrome-dialog-head">
          <h3>数据源详情: {{ selectedSource.name }}</h3>
          <button class="close-btn" type="button" aria-label="关闭采集源详情" @click="closeSourceDetail"><X /></button>
        </div>
        <div class="chrome-dialog-body">
          <div class="push-info">
            <div><span>名称</span><b>{{ selectedSource.name }}</b></div>
            <div><span>唯一标识 (Code)</span><b>{{ selectedSource.code }}</b></div>
            <div><span>当前健康等级</span><span :class="['badge', healthClass(selectedSource.health_level)]">{{ statusLabel(selectedSource.health_level) }}</span></div>
            <div><span>实时采集状态</span><span :class="['badge', healthClass(selectedSource.health_level)]">{{ sourceLiveStatus(selectedSource) }}</span></div>
            <div><span>实时耗时</span><b>{{ formatMs(selectedSource.live_latency_ms) }}</b></div>
            <div><span>最近运行时间</span><b>{{ formatDateTime(selectedSource.latest_run_at) }}</b></div>
            <div class="wide"><span>实时结果</span><b>{{ sourceLiveMessage(selectedSource) }}</b></div>
            <div class="wide"><span>数据源 URL</span><b>{{ selectedSource.source_url || '-' }}</b></div>
            <div class="wide">
              <span>历史运行统计</span>
              <div class="status-counts-tags">
                <span v-for="(count, status) in selectedSource.status_counts" :key="status" :class="['badge', runStatusClass(status)]">
                  {{ statusLabel(status) }}: {{ count }}
                </span>
              </div>
            </div>
          </div>

          <div class="recent-runs-section">
            <h4>本次实时采集预览</h4>
            <div class="recent-runs-list">
              <a
                v-for="preview in selectedSource.live_probe?.items_preview || []"
                :key="`${selectedSource.code}-${preview.source_item_id || preview.title}`"
                class="source-recent-item"
                :href="preview.url || '#'"
                target="_blank"
                rel="noreferrer"
              >
                <div style="width: 100%">
                  <div class="recent-run-info">
                    <span :class="['badge', preview.has_real_evidence ? 'low' : 'high']">{{ preview.has_real_evidence ? '真实来源' : '缺少证据' }}</span>
                    <b>{{ preview.rank ? `${preview.rank}. ` : '' }}{{ preview.title }}</b>
                    <span v-if="preview.raw_hot_score" class="recent-run-time font-mono">热度 {{ preview.raw_hot_score }}</span>
                  </div>
                  <span class="recent-run-id">{{ preview.category || '未分类' }}</span>
                </div>
              </a>
              <div v-if="!(selectedSource.live_probe?.items_preview || []).length" class="empty-hint">本次实时探测没有可预览数据</div>
            </div>
          </div>
          
          <div class="recent-runs-section">
            <h4>最近运行记录</h4>
            <div class="recent-runs-list">
              <div v-for="recent in selectedSource.recent" :key="recent.run_id" class="source-recent-item">
                <div style="width: 100%">
                  <div class="recent-run-info">
                    <span :class="['badge', runStatusClass(recent.status)]">{{ statusLabel(recent.status) }}</span>
                    <b>{{ recent.real_count }}/{{ recent.count }} 条有效</b>
                    <span class="recent-run-time">{{ formatDateTime(recent.run_at) }}</span>
                  </div>
                  <p class="recent-run-error" v-if="recent.error">{{ recent.error }}</p>
                  <span class="recent-run-id" v-else>Run ID: {{ recent.run_id }}</span>
                </div>
              </div>
              <div v-if="!selectedSource.recent?.length" class="empty-hint">暂无最近运行记录</div>
            </div>
          </div>
        </div>
        <div class="chrome-dialog-foot">
          <button class="primary-btn" type="button" @click="closeSourceDetail">确定</button>
        </div>
      </div>
    </div>
  </Transition>
</template>
<script setup lang="ts">


import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, type Component } from 'vue'


import GenerateBriefingModal from '@/components/GenerateBriefingModal.vue'


import EventTable from '@/components/EventTable.vue'


const RunTable = defineAsyncComponent(() => import('@/components/RunTable.vue'))


const KnowledgePage = defineAsyncComponent(() => import('@/views/KnowledgePage.vue'))

const KnowledgeQAPage = defineAsyncComponent(() => import('@/views/KnowledgeQAPage.vue'))
const DataBoardPage = defineAsyncComponent(() => import('@/views/DataBoardPage.vue'))
const FeedbackRecordsPage = defineAsyncComponent(() => import('@/views/FeedbackRecordsPage.vue'))
const SystemLogPage = defineAsyncComponent(() => import('@/views/SystemLogPage.vue'))
const LoginPage = defineAsyncComponent(() => import('@/views/LoginPage.vue'))
const ProfilePage = defineAsyncComponent(() => import('@/views/ProfilePage.vue'))
import ThemeToggle from '@/components/ThemeToggle.vue'

import dayjs from 'dayjs'


import {
  Activity, AlertTriangle, BarChart3, BookOpen, Bot, CalendarDays, Check, Clock3, Code, Cpu, DatabaseZap,
  ExternalLink, Eye, EyeOff, FileText, Flame, Gauge, Heart, History, KeyRound, LineChart, Link2, Menu, MessageSquare, Newspaper,
  Plus, RefreshCw, Search, Send, Settings, ShieldCheck, Sparkles, Star, ThumbsDown, ThumbsUp, Timer,
  UploadCloud, Wifi, X, Zap
} from 'lucide-vue-next'


import {


  clearStoredAdminToken,
  AUTH_EXPIRED_EVENT,

  createEventFeedback,

  deleteEventFeedback,


  deleteModelProvider,

  fetchPlatformHotspots,

  fetchProviderModels,


  generateBriefing,
  generateBriefingAsync,


  getBriefingByDate,


  getCurrentUser,
  getStoredDefaultPage,


  getKnowledgeHealth,


  getKnowledgeIngestRun,


  getModelCallStats,
  getRunDetail,


  getPushConfig,

  getSystemStatus,


  getSchedulerConfig,


  getSchedulerStatus,


  getSourceHealth,


  getTodayBriefing,


  ingestLatestBriefingToKnowledge,


  listBriefings,


  listEvents,


  listKnowledgeIngestRuns,


  listModelProviders,


  listRuns,


  probeModels,


  probeProviderTest,


  pushTodayBriefing,


  regenerateBriefingByDate,
  regenerateBriefingByDateAsync,


  runSchedulerNow,


  saveModelProvider,


  savePushConfig,


  saveSchedulerConfig,


  testModelProvider,


  testPushConfig,


  getStoredAdminToken,
} from '@/api/hotspot'


import type {


  AgentRun,


  AIModelProvider,


  DailyBriefing,


  GenerateBriefingResult,


  AuthLoginResult,

  BriefingTaskStatus,

  EventFeedbackAction,


  HotspotEvent,


  KnowledgeAutoIngestResult,


  KnowledgeIngestRun,


  ModelCallStats,

  PlatformHotspotFetchResult,
  PlatformHotspotItem,


  QQPushConfig,


  SchedulerConfig,


  SchedulerStatus,


  SourceHealthItem,


  SourceHealthReport,


  UserProfile,


} from '@/types/hotspot'





type NavKey = 'dashboard' | 'setup' | 'dataBoard' | 'feedbackRecords' | 'events' | 'history' | 'knowledge' | 'knowledgeQa' | 'sourceHealth' | 'systemLogs' | 'profile' | 'runs' | 'scheduler' | 'modelStats' | 'pushConfig' | 'models'
type NavGroup = 'core' | 'ops'




const navItems: Array<{ key: NavKey; label: string; desc: string; icon: Component; group: NavGroup }> = [


  { key: 'dashboard', label: '今日情报', desc: '抓取、聚合、分析并生成 AI / 科技行业决策简报', icon: Newspaper, group: 'core' },


  { key: 'dataBoard', label: '数据看板', desc: '一屏查看采集、模型、RAG、推送与日志健康度', icon: BarChart3, group: 'core' },

  { key: 'feedbackRecords', label: '反馈记录', desc: '回看有用、无关、收藏和屏蔽记录，支持撤销误操作', icon: ThumbsUp, group: 'core' },


  { key: 'events', label: '热点池', desc: '查看 AI、计算机技术、开源与科技产品热点', icon: Flame, group: 'core' },

  { key: 'history', label: '简报归档', desc: '按日期查看和重生成历史简报', icon: History, group: 'core' },

  { key: 'knowledge', label: '专题知识库', desc: '文档切分、向量检索和带引用问答', icon: BookOpen, group: 'core' },

  { key: 'knowledgeQa', label: '知识问答', desc: '独立 RAG 问答助手，支持文档选择、多轮追问和引用追溯', icon: Bot, group: 'core' },

  { key: 'sourceHealth', label: '采集源状态', desc: '监控真实采集、失败和兜底数据比例', icon: ShieldCheck, group: 'ops' },

  { key: 'systemLogs', label: '系统日志', desc: '查看启动、任务、接口异常和人工操作日志', icon: Gauge, group: 'ops' },


  { key: 'profile', label: '个人中心', desc: '查看登录身份、权限范围与退出登录', icon: KeyRound, group: 'ops' },


  { key: 'runs', label: '运行记录', desc: 'Agent run 日志和错误排查', icon: Activity, group: 'ops' },


  { key: 'scheduler', label: '自动任务', desc: '服务器部署后的每日定时任务', icon: CalendarDays, group: 'ops' },


  { key: 'modelStats', label: '模型统计', desc: 'LLM 调用成功率、延迟和缓存命中', icon: LineChart, group: 'ops' },


  { key: 'pushConfig', label: 'QQ 推送', desc: '配置 OneBot / QQ 机器人推送', icon: Send, group: 'ops' },


  { key: 'models', label: '模型配置', desc: '配置模型、获取模型列表、测试连通性和优先级', icon: Settings, group: 'ops' },


]





const activePage = ref<NavKey>((getStoredDefaultPage() as NavKey) || 'dashboard')


const authChecked = ref(false)
const isAuthenticated = ref(false)
const currentUser = ref<UserProfile | null>(null)


const collapsed = ref(false)

const mobileMenuOpen = ref(false)
const mobileSidebarRef = ref<HTMLElement | null>(null)
const mobileMenuButtonRef = ref<HTMLButtonElement | null>(null)


const loading = ref(false)


const generating = ref(false)


const generatingStep = ref(0)


const generatingSteps = [


  '启动热点采集任务',


  '请求真实数据源并记录健康状态',


  '清洗、去重、热度评分',


  'RAG 检索并调用模型分析',


  '生成 Markdown 今日早报',


  '自动写入知识库 / Qdrant',


  '刷新前端看板与可观测数据',


]


let generatingTimer: number | undefined


const generatingAutoIngest = ref<KnowledgeAutoIngestResult | null>(null)


const generatingIngestRun = ref<KnowledgeIngestRun | null>(null)


const generatingTask = ref<BriefingTaskStatus | null>(null)


const pushing = ref(false)


const message = ref('')


const errorMessage = ref('')





const todayBriefing = ref<DailyBriefing | null>(null)


const events = ref<HotspotEvent[]>([])


const runs = ref<AgentRun[]>([])


const sourceHealth = ref<SourceHealthReport | null>(null)

const systemStatus = ref<Record<string, any> | null>(null)


const platformHotspots = ref<PlatformHotspotFetchResult | null>(null)


const platformFetching = ref(false)


const selectedSourceCode = ref('')


const history = ref<DailyBriefing[]>([])
const selectedHistoryDate = ref('')
const selectedBriefing = ref<DailyBriefing | null>(null)
const historyViewMode = ref<'rendered' | 'source'>('rendered')
const historySearchQuery = ref('')
const filteredHistory = computed(() => {
  const query = historySearchQuery.value.trim().toLowerCase()
  if (!query) return history.value
  return history.value.filter(item => {
    const matchDate = (item.briefing_date || '').toLowerCase().includes(query)
    const matchTitle = (item.title || '').toLowerCase().includes(query)
    const matchSummary = (item.summary || '').toLowerCase().includes(query)
    return matchDate || matchTitle || matchSummary
  })
})

const showPushToken = ref(false)

const knowledgeHealth = ref<Record<string, any> | null>(null)


const ingestRuns = ref<KnowledgeIngestRun[]>([])


const schedulerStatus = ref<SchedulerStatus | null>(null)


const schedulerForm = ref<SchedulerConfig>(defaultScheduler())


const pushForm = ref<QQPushConfig>(defaultPush())


const modelStats = ref<ModelCallStats | null>(null)


const providers = ref<AIModelProvider[]>([])


const providerModelOptions = ref<Record<string, string[]>>({})


const providerMessages = ref<Record<string, string>>({})
const setupLastOpened = ref(localStorage.getItem('HOTSPOT_SETUP_OPENED') || '')


const isEditModalOpen = ref(false)
const isSourceDetailOpen = ref(false)



const editingProvider = ref<AIModelProvider | null>(null)
const showApiKey = ref(false)
const isTestingProvider = ref(false)
const isFetchingModels = ref(false)


const eventFilters = ref({ category: '', risk_level: '' })


const toasts = ref<Array<{ id: number; message: string; type: 'success' | 'error' | 'info' }>>([])


let toastSeed = 1


const feedbackSavingKey = ref('')


const feedbackActions: Array<{ value: EventFeedbackAction; label: string; icon: Component; tone: 'good' | 'bad' | 'star' | 'block'; activeText: string }> = [
  { value: 'USEFUL', label: '有用', icon: ThumbsUp, tone: 'good', activeText: '已标有用' },
  { value: 'IRRELEVANT', label: '无关', icon: ThumbsDown, tone: 'bad', activeText: '已标无关' },
  { value: 'FAVORITE', label: '收藏', icon: Star, tone: 'star', activeText: '已收藏' },
  { value: 'BLOCK', label: '屏蔽', icon: EyeOff, tone: 'block', activeText: '已屏蔽' },
]


const fakeSourceCodes = new Set(['sample', 'demo', 'mock', 'fake', 'placeholder', 'test'])




const currentNav = computed(() => {
  if (activePage.value === 'setup') {
    return { key: 'setup', label: '首次配置', desc: '完成账号、模型、数据源、早报和知识库的首轮配置', icon: ShieldCheck, group: 'ops' } as const
  }
  return navItems.find((item) => item.key === activePage.value) || navItems[0]
})


const today = computed(() => new Date().toISOString().slice(0, 10))


const rawDashboardEvents = computed<HotspotEvent[]>(() => {


  const rawEvents = todayBriefing.value?.raw_json?.events


  return Array.isArray(rawEvents) && rawEvents.length ? rawEvents : events.value


})


const dashboardEvents = computed<HotspotEvent[]>(() => rawDashboardEvents.value.filter((event) => hasVerifiableEvidence(event) && !event.feedback?.is_blocked))


const briefingMarkdown = computed(() => todayBriefing.value?.markdown || '暂无今日早报。点击右上角“生成今日早报”。')


const highRiskCount = computed(() => dashboardEvents.value.filter((event) => event.risk_level === 'HIGH').length)


const topFive = computed(() => [...dashboardEvents.value].sort((a, b) => Number(displayHeatScore(b) || 0) - Number(displayHeatScore(a) || 0)).slice(0, 5))


const intelligenceCards = computed(() => topFive.value.slice(0, 6))


const eventCategories = computed(() => Array.from(new Set(events.value.map((event) => event.category).filter(Boolean) as string[])).sort())


const categoryStats = computed(() => {


  const total = dashboardEvents.value.length || 1


  const map = new Map<string, number>()


  for (const event of dashboardEvents.value) map.set(event.category || '综合', (map.get(event.category || '综合') || 0) + 1)


  return Array.from(map.entries()).map(([name, count]) => ({ name, count, percent: Math.round((count / total) * 100) })).sort((a, b) => b.count - a.count)


})

const deliveryGrade = computed(() => {
  const hasBriefing = Boolean(todayBriefing.value)
  const eventCount = dashboardEvents.value.length
  const health = sourceHealth.value
  const avgSuccess = Number(health?.avg_success_rate || 0)
  const down = Number(health?.down_sources || 0)
  const unstable = Number(health?.degraded_sources || 0)
  let score = 42
  if (hasBriefing) score += 18
  score += Math.min(20, eventCount * 0.8)
  score += Math.min(15, avgSuccess * 0.15)
  score -= down * 8 + unstable * 2
  score = Math.max(0, Math.min(100, Math.round(score)))
  if (score >= 80) return { score, level: 'low', label: '可交付', hint: '数据、简报与知识链路基本健康' }
  if (score >= 60) return { score, level: 'medium', label: '可演示', hint: '可以使用，但仍需关注数据源或简报完整度' }
  return { score, level: 'high', label: '需处理', hint: '请先生成简报并检查采集源健康' }
})

const executiveInsights = computed(() => [
  {
    title: '核心热点',
    desc: topFive.value[0]?.title || '暂无热点，请先生成今日情报。',
    icon: Flame,
    tone: 'blue',
  },
  {
    title: '数据可信度',
    desc: sourceHealth.value
      ? `平均成功率 ${formatPercent(sourceHealth.value.avg_success_rate)}，异常源 ${sourceHealth.value.down_sources + sourceHealth.value.degraded_sources} 个`
      : '等待采集源健康检测。',
    icon: ShieldCheck,
    tone: (sourceHealth.value?.down_sources || 0) > 0 ? 'red' : 'green',
  },
  {
    title: '下一步动作',
    desc: todayBriefing.value ? '复制简报、入库沉淀，或进入热点池做专题筛选。' : '先生成今日情报，再查看 AI / 科技热点池。',
    icon: Sparkles,
    tone: 'purple',
  },
])



const enabledProviderCount = computed(() => providers.value.filter((provider) => provider.enabled).length)

const setupSteps = computed(() => [
  {
    key: 'token',
    title: '账号安全',
    desc: systemStatus.value?.api_auth_enabled ? '后台 API 已启用管理凭据保护，前台只保留账号密码登录。' : '建议开启 API_AUTH_ENABLED，并替换默认 ADMIN_TOKEN。',
    done: Boolean(systemStatus.value?.api_auth_enabled),
    icon: KeyRound,
    page: 'profile' as NavKey,
    action: '查看安全',
  },
  {
    key: 'model',
    title: '模型通道',
    desc: enabledProviderCount.value ? `已启用 ${enabledProviderCount.value} 个模型通道，可进入模型配置测试连通性。` : '至少启用一个 OpenAI-compatible 模型通道。',
    done: enabledProviderCount.value > 0,
    icon: Bot,
    page: 'models' as NavKey,
    action: '配置模型',
  },
  {
    key: 'sources',
    title: '数据源健康',
    desc: sourceHealth.value ? `当前启用 ${sourceHealth.value.enabled_sources} 个源，异常 ${sourceHealth.value.down_sources + sourceHealth.value.degraded_sources} 个。` : '先刷新采集源状态，确认真实公开源可用。',
    done: Boolean(sourceHealth.value && sourceHealth.value.enabled_sources > 0 && sourceHealth.value.down_sources === 0),
    icon: ShieldCheck,
    page: 'sourceHealth' as NavKey,
    action: '检查数据源',
  },
  {
    key: 'briefing',
    title: '生成早报',
    desc: todayBriefing.value ? `今日早报状态：${statusLabel(todayBriefing.value.status)}` : '点击生成今日情报，建立首份可展示简报。',
    done: Boolean(todayBriefing.value),
    icon: Newspaper,
    page: 'dashboard' as NavKey,
    action: '生成情报',
  },
  {
    key: 'knowledge',
    title: '知识库 / 推送',
    desc: knowledgeHealth.value?.ok ? '知识库连通正常，可继续配置 QQ 推送。' : '建议测试 Embedding 与 Qdrant，必要时配置推送。',
    done: Boolean(knowledgeHealth.value?.ok),
    icon: DatabaseZap,
    page: 'knowledge' as NavKey,
    action: '检查知识库',
  },
])

const setupCompletion = computed(() => {
  const steps = setupSteps.value
  const done = steps.filter((step) => step.done).length
  return {
    percent: steps.length ? Math.round((done / steps.length) * 100) : 0,
    missing: steps.filter((step) => !step.done),
  }
})

const setupNudgeTitle = computed(() => {
  if (deliveryGrade.value.score >= 80) {
    return `交付核心已就绪，剩余 ${setupCompletion.value.missing.length} 项可选增强`
  }
  return `首次配置还差 ${setupCompletion.value.missing.length} 步`
})

const setupNudgeDesc = computed(() => {
  if (deliveryGrade.value.score >= 80) {
    return '当前真实数据、早报、知识库和运维链路已经可演示；剩余项多为 QQ 推送、正式域名或体验增强，可按交付场景继续补齐。'
  }
  return '建议完成账号安全、模型、数据源、知识库和推送配置，让交付演示更稳定。'
})

const selectedSource = computed<SourceHealthItem | null>(() => (sourceHealth.value?.items || []).find((item) => item.code === selectedSourceCode.value) || sourceHealth.value?.items?.[0] || null)


const generatingIngestStatus = computed(() => generatingIngestRun.value?.status || generatingAutoIngest.value?.status || '')


const generatingIngestMessage = computed(() => {


  const auto = generatingAutoIngest.value


  const run = generatingIngestRun.value


  if (!auto) return ''


  if (!auto.enabled) return '当前配置未启用自动入库，早报已生成但不会写入知识库。'


  if (!auto.queued) return auto.error_message || '自动入库未入队，请到知识库页面手动导入。'


  if (run?.status === 'SUCCESS') {


    return `已写入知识库：${run.document_title || '历史早报'}，${run.chunk_count || 0} 个分块。`


  }


  if (run?.status === 'FAILED') {


    return run.error_message || '知识库入库失败，请在任务列表查看错误。'


  }


  return `入库任务 #${auto.run_id || '-'} 已排队，当前状态 ${statusLabel(run?.status || auto.status || 'QUEUED')}。`


})





function defaultPush(): QQPushConfig {


  return {


    channel: 'qq_bot',


    enabled: false,


    onebot_api_base: 'http://127.0.0.1:3000',


    target_type: 'private',


    user_id: '',


    group_id: '',


    access_token: '',


    retry_times: 2,


    timeout_seconds: 10,


    max_chars: 1800,


    allow_partial_success: true,


  }


}





function defaultScheduler(): SchedulerConfig {


  return {


    enabled: false,


    hour: 8,


    minute: 30,


    timezone: 'Asia/Shanghai',


    allow_rerun_same_day: false,


    lock_ttl_minutes: 60,


    retry_times: 2,


    retry_delay_seconds: 60,


    misfire_grace_seconds: 300,


    coalesce: true,


    max_instances: 1,


  }


}





function defaultProvider(): AIModelProvider {


  return {


    code: `provider_${Date.now()}`,


    name: '新模型通道',


    base_url: '',


    api_key: '',


    model: '',


    priority: 10,


    enabled: true,


    requires_api_key: false,


    timeout_seconds: 60,


    max_tokens: 1200,


    temperature: 0.2,


    input_cost_per_million: 0,


    output_cost_per_million: 0,


    note: '',


  }


}





async function switchPage(page: NavKey) {
  const openedFromMobileMenu = mobileMenuOpen.value
  if (page === 'setup') {
    setupLastOpened.value = new Date().toISOString()
    localStorage.setItem('HOTSPOT_SETUP_OPENED', setupLastOpened.value)
  }


  activePage.value = page
  mobileMenuOpen.value = false


  await refreshCurrentPage()

  if (openedFromMobileMenu) {
    await nextTick()
    document.getElementById('main-content')?.focus()
  }


}

async function openMobileMenu() {
  mobileMenuOpen.value = true
  await nextTick()
  mobileSidebarRef.value?.querySelector<HTMLElement>('.nav-btn')?.focus()
}

async function closeMobileMenu() {
  mobileMenuOpen.value = false
  await nextTick()
  mobileMenuButtonRef.value?.focus()
}

function trapMobileMenuFocus(event: KeyboardEvent) {
  const sidebar = mobileSidebarRef.value
  if (!mobileMenuOpen.value || !sidebar) return
  const focusable = Array.from(sidebar.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
    .filter((element) => element.getClientRects().length > 0)
  if (!focusable.length) return

  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}





const knowledgePageRef = ref<any>(null)

const knowledgeQaPageRef = ref<any>(null)
const dataBoardPageRef = ref<any>(null)
const feedbackRecordsPageRef = ref<any>(null)
const systemLogPageRef = ref<any>(null)




async function initializeApp() {
  authChecked.value = false
  errorMessage.value = ''
  message.value = ''
  try {
    if (getStoredAdminToken()) {
      currentUser.value = await getCurrentUser()
      isAuthenticated.value = true
      authChecked.value = true
      await loadDashboard()
    } else {
      isAuthenticated.value = false
      currentUser.value = null
      authChecked.value = true
    }
  } catch (error) {
    const shouldReportError = Boolean(getStoredAdminToken())
    clearStoredAdminToken()
    currentUser.value = null
    isAuthenticated.value = false
    authChecked.value = true
    if (shouldReportError) setError(error)
  }
}


async function handleLoginSuccess(result: AuthLoginResult) {
  currentUser.value = result.profile
  isAuthenticated.value = true
  authChecked.value = true
  activePage.value = 'dashboard'
  mobileMenuOpen.value = false
  setMessage(`登录成功，欢迎 ${result.profile.display_name || result.profile.username}`)
  await loadDashboard()
}


function handleLogout() {
  clearStoredAdminToken()
  isAuthenticated.value = false
  currentUser.value = null
  activePage.value = 'dashboard'
  mobileMenuOpen.value = false
  isEditModalOpen.value = false
  isSourceDetailOpen.value = false
  message.value = ''
  errorMessage.value = ''
}


function handleAuthExpired(event: Event) {
  const detail = (event as CustomEvent<{ message?: string }>).detail
  clearStoredAdminToken()
  currentUser.value = null
  isAuthenticated.value = false
  authChecked.value = true
  activePage.value = 'dashboard'
  mobileMenuOpen.value = false
  isEditModalOpen.value = false
  isSourceDetailOpen.value = false
  setError(detail?.message || '登录已过期，请重新登录。')
}


async function refreshProfile() {
  await runTask(async () => {
    currentUser.value = await getCurrentUser()
    setMessage('身份信息已刷新')
  })
}




async function refreshCurrentPage() {


  if (activePage.value === 'dashboard' || activePage.value === 'setup') return loadDashboard()


  if (activePage.value === 'dataBoard') return dataBoardPageRef.value?.refresh()

  if (activePage.value === 'feedbackRecords') return feedbackRecordsPageRef.value?.refresh()


  if (activePage.value === 'events') return loadEventsPage()

  if (activePage.value === 'history') return loadHistoryPage()

  if (activePage.value === 'knowledge') return knowledgePageRef.value?.refresh()

  if (activePage.value === 'knowledgeQa') return knowledgeQaPageRef.value?.refresh()

  if (activePage.value === 'sourceHealth') return loadSourceHealthPage()

  if (activePage.value === 'systemLogs') return systemLogPageRef.value?.refresh()

  if (activePage.value === 'profile') return refreshProfile()

  if (activePage.value === 'runs') return loadRunsPage()


  if (activePage.value === 'scheduler') return loadSchedulerPage()


  if (activePage.value === 'modelStats') return loadModelStatsPage()


  if (activePage.value === 'pushConfig') return loadPushConfigPage()


  if (activePage.value === 'models') return loadModelsPage()


}





async function runTask(task: () => Promise<void>) {


  loading.value = true


  try {


    await task()


  } catch (error) {


    setError(error)


  } finally {


    loading.value = false


  }


}





async function loadDashboard() {


  await runTask(async () => {


    const [status, briefing, health, runRows, eventRows, kHealth, providerRows] = await Promise.allSettled([


      getSystemStatus(),


      getTodayBriefing(),


      getSourceHealth(30),


      listRuns(10),


      listEvents({ limit: 50 }),


      getKnowledgeHealth(),


      listModelProviders(),


    ])


    if (status.status === 'fulfilled') systemStatus.value = status.value


    if (briefing.status === 'fulfilled') todayBriefing.value = briefing.value


    if (health.status === 'fulfilled') sourceHealth.value = health.value


    if (runRows.status === 'fulfilled') runs.value = runRows.value


    if (eventRows.status === 'fulfilled') events.value = eventRows.value


    if (kHealth.status === 'fulfilled') knowledgeHealth.value = kHealth.value


    if (providerRows.status === 'fulfilled') providers.value = providerRows.value.map((row: AIModelProvider) => ({ ...row, api_key: '' }))


  })


}





async function loadEventsPage() {


  await runTask(async () => {


    const [dbRows, briefing] = await Promise.allSettled([


      listEvents({ limit: 200, category: eventFilters.value.category || undefined, risk_level: eventFilters.value.risk_level || undefined }),


      getTodayBriefing(),


    ])


    const rawEvents = briefing.status === 'fulfilled' ? briefing.value?.raw_json?.events : []


    if (Array.isArray(rawEvents) && rawEvents.length) {


      events.value = rawEvents


        .filter((event: HotspotEvent) => !eventFilters.value.category || event.category === eventFilters.value.category)


        .filter((event: HotspotEvent) => !eventFilters.value.risk_level || event.risk_level === eventFilters.value.risk_level)


        .slice(0, 200)


    } else if (dbRows.status === 'fulfilled') {


      events.value = dbRows.value


    }


  })


}





async function loadHistoryPage() {


  await runTask(async () => {


    history.value = await listBriefings(50)


    if (!selectedHistoryDate.value && history.value[0]?.briefing_date) await selectHistory(history.value[0].briefing_date)


  })


}





async function selectHistory(date?: string) {


  if (!date) return


  selectedHistoryDate.value = date


  try {


    selectedBriefing.value = await getBriefingByDate(date)


  } catch (error) {


    setError(error)


  }


}








async function loadSourceHealthPage() {


  await runTask(async () => {


    sourceHealth.value = await getSourceHealth(50, true, 10, 12)


    if (!selectedSourceCode.value && sourceHealth.value?.items?.[0]) selectedSourceCode.value = sourceHealth.value.items[0].code


  })


}





async function handleFetchPlatforms(sources: string[] = ['github', 'huggingface', 'devto']) {
  platformFetching.value = true
  errorMessage.value = ''
  try {
    platformHotspots.value = await fetchPlatformHotspots({ sources, limit: 20, timeout: 40 })
    const total = platformHotspots.value?.total ?? 0
    setMessage(`\u5373\u65f6\u6293\u53d6\u5b8c\u6210\uff1a\u5171 ${total} \u6761\u771f\u5b9e\u516c\u5f00\u6570\u636e`)
  } catch (error) {
    setError(error)
  } finally {
    platformFetching.value = false
  }
}

function platformItemCategory(item: PlatformHotspotItem): string {
  const category = item.raw_payload?.system_category
  if (category) return String(category)
  const tag = item.tags?.find((value) => value.includes('/') || value.includes('AI') || value.includes('科技') || value.includes('开源'))
  return tag || '系统关注'
}


async function loadRunsPage() {


  await runTask(async () => {


    const [runRows, ingestRows] = await Promise.allSettled([


      listRuns(100),


      listKnowledgeIngestRuns({ limit: 100 }),


    ])


    if (runRows.status === 'fulfilled') runs.value = runRows.value


    if (ingestRows.status === 'fulfilled') ingestRuns.value = ingestRows.value


  })


}





async function loadSchedulerPage() {


  await runTask(async () => {


    schedulerForm.value = { ...defaultScheduler(), ...(await getSchedulerConfig()) }


    schedulerStatus.value = await getSchedulerStatus()


  })


}





async function loadModelStatsPage() {


  await runTask(async () => {


    modelStats.value = await getModelCallStats(80)


  })


}





async function loadPushConfigPage() {


  await runTask(async () => {


    pushForm.value = { ...defaultPush(), ...(await getPushConfig()), access_token: '' }


  })


}





async function loadModelsPage() {


  await runTask(async () => {


    const rows = await listModelProviders()


    providers.value = rows.map((row: AIModelProvider) => ({ ...row, api_key: '' }))


  })


}





function briefingEventCount(result: GenerateBriefingResult): number | string {


  return result.total_events ?? result.briefing?.events?.length ?? '-'


}


function taskEventCount(task?: BriefingTaskStatus | null): number | string {


  return task?.total_events ?? task?.meta?.api_result?.total_events ?? '-'


}





function knowledgeIngestToastText(auto?: KnowledgeAutoIngestResult): string {


  if (!auto) return ''


  if (auto.queued) return `，知识库入库任务 #${auto.run_id || '-'} 已入队`


  if (auto.enabled) return '，知识库自动入库未入队'


  return '，知识库自动入库未启用'


}





function runKnowledgeIngest(run: AgentRun): KnowledgeAutoIngestResult | null {


  return (run.meta?.knowledge_ingest as KnowledgeAutoIngestResult | undefined) || null


}





function runKnowledgeIngestLive(run: AgentRun): KnowledgeIngestRun | null {


  const auto = runKnowledgeIngest(run)


  if (!auto?.run_id) return null


  return ingestRuns.value.find((row) => row.id === auto.run_id) || null


}





function runKnowledgeIngestStatus(run: AgentRun): string {


  const auto = runKnowledgeIngest(run)


  const live = runKnowledgeIngestLive(run)


  return live?.status || auto?.status || (auto?.queued ? 'QUEUED' : 'SKIPPED')


}





function runKnowledgeIngestLabel(run: AgentRun): string {


  const auto = runKnowledgeIngest(run)


  return `#${auto?.run_id || '-'} · ${runKnowledgeIngestStatus(run)}`


}





function runKnowledgeIngestHint(run: AgentRun): string {


  const auto = runKnowledgeIngest(run)


  const live = runKnowledgeIngestLive(run)


  if (!auto) return '未触发'


  if (live?.status === 'SUCCESS') return `${live.document_title || '历史早报'}，${live.chunk_count || 0} 个分块`


  if (live?.status === 'FAILED') return live.error_message || '入库失败'


  if (!auto.queued) return auto.error_message || '未入队'


  return auto.duplicate_policy || '异步入库中'


}





function sleep(ms: number) {


  return new Promise((resolve) => window.setTimeout(resolve, ms))


}





async function trackGeneratedKnowledgeIngest(result: GenerateBriefingResult) {


  const auto = result.knowledge_ingest


  if (!auto) {


    generatingAutoIngest.value = { enabled: false, queued: false, status: 'SKIPPED' }


    return


  }





  generatingAutoIngest.value = auto


  generatingIngestRun.value = null


  generatingTask.value = null


  generatingStep.value = Math.max(0, generatingSteps.length - 2)





  if (!auto.queued || !auto.run_id) return





  for (let i = 0; i < 20; i += 1) {


    await sleep(i === 0 ? 500 : 1500)


    try {


      const run = await getKnowledgeIngestRun(auto.run_id)


      generatingIngestRun.value = run


      if (run.status === 'SUCCESS' || run.status === 'FAILED') break


    } catch (error) {


      generatingIngestRun.value = {


        id: auto.run_id,


        status: 'FAILED',


        chunk_count: 0,


        error_message: error instanceof Error ? error.message : String(error),


      }


      break


    }


  }





  try {


    ingestRuns.value = await listKnowledgeIngestRuns({ limit: 20 })


  } catch {


    // 入库任务列表刷新失败不影响早报生成结果展示。


  }


}


async function pollBriefingTask(runId: string): Promise<BriefingTaskStatus> {
  let latest: BriefingTaskStatus | null = null
  for (let i = 0; i < 90; i += 1) {
    await sleep(i === 0 ? 500 : 2000)
    latest = await getRunDetail(runId)
    generatingTask.value = latest
    const progress = Number(latest.progress || 0)
    const mappedStep = Math.min(generatingSteps.length - 2, Math.max(1, Math.floor((progress / 100) * (generatingSteps.length - 1))))
    generatingStep.value = Math.max(generatingStep.value, mappedStep)
    if (['SUCCESS', 'FAILED', 'SKIPPED'].includes(String(latest.status || '').toUpperCase())) break
  }
  if (!latest) throw new Error('未能获取早报任务状态。')
  const finalStatus = String(latest.status || '').toUpperCase()
  if (!['SUCCESS', 'FAILED', 'SKIPPED'].includes(finalStatus)) {
    throw new Error(`任务仍在后台执行，但页面等待已超时。请到“运行记录”查看任务 ${runId} 的最新状态。`)
  }
  return latest
}


function hydrateKnowledgeIngestFromTask(task: BriefingTaskStatus) {
  const auto = task.knowledge_ingest || task.meta?.knowledge_ingest
  if (auto) {
    generatingAutoIngest.value = auto
  }
}


async function finishAsyncBriefingTask(task: BriefingTaskStatus, successMessage: string) {
  hydrateKnowledgeIngestFromTask(task)
  if (generatingAutoIngest.value?.queued && generatingAutoIngest.value.run_id) {
    await trackGeneratedKnowledgeIngest({ status: task.status, knowledge_ingest: generatingAutoIngest.value })
  }
  generatingStep.value = generatingSteps.length - 1
  const status = String(task.status || '').toUpperCase()
  if (status === 'FAILED') {
    throw new Error(task.error_message || task.meta?.api_result?.message || '早报异步任务失败。')
  }
  if (status === 'SKIPPED') {
    setMessage(task.message || '早报任务已跳过，没有重复生成。')
    return
  }
  if (status !== 'SUCCESS') {
    throw new Error(`早报任务尚未完成，当前状态：${statusLabel(task.status || 'UNKNOWN')}`)
  }
  setMessage(successMessage)
}





async function handleGenerate() {


  startGeneratingModal()


  try {


    const queued = await generateBriefingAsync({ trigger: 'manual' })
    generatingTask.value = queued
    setMessage(queued.reused ? `已复用正在执行的早报任务：${queued.run_id}` : `早报任务已入队：${queued.run_id}`)
    const task = await pollBriefingTask(queued.run_id)
    await finishAsyncBriefingTask(task, `早报生成完成：${statusLabel(task.status || 'SUCCESS')}，事件数 ${taskEventCount(task)}${knowledgeIngestToastText(task.knowledge_ingest || task.meta?.knowledge_ingest)}`)


    await loadDashboard()


  } catch (error) {


    setError(error)


  } finally {


    stopGeneratingModal()


  }


}





async function handlePush() {


  pushing.value = true


  try {


    const result = await pushTodayBriefing()


    if (result.ok) {
      setMessage('QQ 机器人推送成功')
    } else {
      setError(`推送失败：${result.message || result.data?.message || '未知错误'}`)
    }


  } catch (error) {


    setError(error)


  } finally {


    pushing.value = false


  }


}





async function handleIngestLatest() {


  await runTask(async () => {


    const result = await ingestLatestBriefingToKnowledge()


    const doc = result.document || result


    setMessage(`最新早报已写入知识库：${doc.title || '知识库文档'}`)


  })


}





async function handleRegenerateHistory() {


  if (!selectedHistoryDate.value) return


  startGeneratingModal()


  try {


    const queued = await regenerateBriefingByDateAsync(selectedHistoryDate.value)
    generatingTask.value = queued
    setMessage(`历史早报重生成任务已入队：${queued.run_id}`)
    const task = await pollBriefingTask(queued.run_id)
    await finishAsyncBriefingTask(task, `历史早报已重生成：${statusLabel(task.status || 'SUCCESS')}${knowledgeIngestToastText(task.knowledge_ingest || task.meta?.knowledge_ingest)}`)


    await selectHistory(selectedHistoryDate.value)


  } catch (error) {


    setError(error)


  } finally {


    stopGeneratingModal()


  }


}





async function handleSaveScheduler() {


  await runTask(async () => {


    await saveSchedulerConfig(schedulerForm.value)


    setMessage('自动任务配置已保存')


    await loadSchedulerPage()


  })


}





async function handleRunScheduler() {


  await runTask(async () => {


    const result = await runSchedulerNow(true)


    setMessage(`调度任务已触发：${statusLabel(result.status || 'OK')}`)


    await loadSchedulerPage()


  })


}





async function handleSavePush() {


  await runTask(async () => {


    pushForm.value = { ...defaultPush(), ...(await savePushConfig(pushForm.value)), access_token: '' }


    setMessage('QQ 推送配置已保存')


  })


}





async function handleTestPush() {


  await runTask(async () => {


    const result = await testPushConfig(pushForm.value)


    if (result.ok) {
      setMessage(`连通成功：${result.message || '正常'}`)
    } else {
      setError(`连通失败：${result.message || '未知错误'}`)
    }


  })


}





function providerKey(provider: AIModelProvider): string {


  return provider.id ? `id-${provider.id}` : `new-${provider.code}`


}

function providerCostLabel(provider: AIModelProvider): string {
  const input = Number(provider.input_cost_per_million || 0)
  const output = Number(provider.output_cost_per_million || 0)
  if (!input && !output) return '未设置'
  return `输入 ${formatUsd(input)} · 输出 ${formatUsd(output)}`
}





function providerOptions(provider: AIModelProvider): string[] {


  return providerModelOptions.value[providerKey(provider)] || []


}





async function handleFetchModels(provider: AIModelProvider) {


  const key = providerKey(provider)


  await runTask(async () => {


    const rows = provider.id ? await fetchProviderModels(provider.id) : await probeModels(provider)


    providerModelOptions.value[key] = rows


    const msg = rows.length ? `已获取 ${rows.length} 个模型，请下拉选择。` : '接口可用，但没有返回模型列表。'


    if (!provider.model && rows[0]) provider.model = rows[0]


    setMessage(msg)


  })


}





async function handleTestProvider(provider: AIModelProvider) {


  await runTask(async () => {


    const result = provider.id ? await testModelProvider(provider.id) : await probeProviderTest(provider)


    const msg = `${result.ok ? '测试成功' : '测试失败'}：${result.message || ''} ${result.latency_ms ? `(${result.latency_ms}ms)` : ''}`


    if (result.ok) {


      setMessage(msg)


    } else {


      setError(msg)


    }


  })


}





function openSourceDetail(item: any) {

  selectedSourceCode.value = item.code

  isSourceDetailOpen.value = true

}



function closeSourceDetail() {

  isSourceDetailOpen.value = false

}



function runStatusClass(status: string): string {

  if (status === 'SUCCESS') return 'low'

  if (status === 'FAILED') return 'high'

  if (status === 'FALLBACK') return 'medium'

  return 'medium'

}





function openEditModal(provider: AIModelProvider) {
  editingProvider.value = JSON.parse(JSON.stringify(provider))
  showApiKey.value = false
  isTestingProvider.value = false
  isFetchingModels.value = false
  isEditModalOpen.value = true
}

function closeEditModal() {
  editingProvider.value = null
  showApiKey.value = false
  isTestingProvider.value = false
  isFetchingModels.value = false
  isEditModalOpen.value = false
}

async function onFetchModelsClick(provider: AIModelProvider) {
  isFetchingModels.value = true
  try {
    await handleFetchModels(provider)
  } finally {
    isFetchingModels.value = false
  }
}

async function onTestProviderClick(provider: AIModelProvider) {
  isTestingProvider.value = true
  try {
    await handleTestProvider(provider)
  } finally {
    isTestingProvider.value = false
  }
}

function onModelSelectChange(event: Event) {
  const target = event.target as HTMLSelectElement
  if (target.value && editingProvider.value) {
    editingProvider.value.model = target.value
  }
}





async function handleSaveEditingProvider() {


  if (!editingProvider.value) return


  await runTask(async () => {


    const saved = await saveModelProvider(editingProvider.value!)


    setMessage(`模型通道已保存：${saved.name || saved.code}`)


    closeEditModal()


    await loadModelsPage()


  })


}





async function toggleProviderEnabled(provider: AIModelProvider) {
  await runTask(async () => {
    const updated = { ...provider, enabled: !provider.enabled, api_key: '' }
    const saved = await saveModelProvider(updated)
    setMessage(`已${saved.enabled ? '启用' : '禁用'}通道：${saved.name || saved.code}`)
    await loadModelsPage()
  })
}

async function handleDeleteProvider(provider: AIModelProvider) {


  if (!provider.id || !window.confirm(`确认永久删除模型通道「${provider.name || provider.code}」？\n\n删除后不会在下次启动时自动恢复，需要时可重新添加同 code。`)) return


  await runTask(async () => {


    await deleteModelProvider(provider.id as number)

    providers.value = providers.value.filter((item) => item.id !== provider.id)

    setMessage(`模型通道已删除：${provider.name || provider.code}`)


    await loadModelsPage()


  })


}





async function copyText(text: string) {


  if (!text) return


  await navigator.clipboard.writeText(text)


  setMessage('已复制到剪贴板')


}





function showToast(message: string, type: 'success' | 'error' | 'info' = 'info') {


  const id = toastSeed++


  toasts.value.push({ id, message, type })


  window.setTimeout(() => removeToast(id), 4000)


}





function removeToast(id: number) {


  toasts.value = toasts.value.filter((toast) => toast.id !== id)


}





function setMessage(text: string) {


  message.value = text


  errorMessage.value = ''


  showToast(text, 'success')


  window.setTimeout(() => {


    if (message.value === text) message.value = ''


  }, 4500)


}





function setError(error: unknown) {


  const text = normalizeError(error)


  errorMessage.value = text


  message.value = ''


  showToast(text, 'error')


}





function normalizeError(error: unknown): string {


  if (typeof error === 'object' && error !== null) {


    const e = error as { response?: { data?: { detail?: unknown; message?: unknown } }; message?: string }


    const detail = e.response?.data?.detail || e.response?.data?.message


    if (typeof detail === 'string') return detail


    if (Array.isArray(detail)) return detail.map((item) => JSON.stringify(item)).join('; ')


    if (e.message) return e.message


  }


  return String(error)


}





function riskClass(risk?: string): string {


  if (risk === 'HIGH') return 'high'


  if (risk === 'MEDIUM') return 'medium'


  return 'low'


}


function credibilityTone(level?: string): string {
  if (level === 'HIGH') return 'high-score'
  if (level === 'MEDIUM') return 'mid-score'
  return 'low-score'
}


function estimatedCredibility(event: HotspotEvent): { score: number; level: string } {
  const sources = new Set(event.source_codes || [])
  const strong = ['github', 'hackernews', 'arxiv_ai', 'huggingface', 'devto']
  const general: string[] = []
  let score = 35
  score += Math.min(sources.size, 4) * 12
  score += strong.filter((code) => sources.has(code)).length * 10
  score += general.filter((code) => sources.has(code)).length * 4
  if (event.rag_references?.length) score += Math.min(event.rag_references.length, 3) * 5
  if (event.items?.some((item) => item.url)) score += 6
  score = Math.max(0, Math.min(100, Math.round(score)))
  return {
    score,
    level: score >= 75 ? 'HIGH' : score >= 55 ? 'MEDIUM' : 'LOW',
  }
}


function formatCredibility(event: HotspotEvent): string {
  const fallback = estimatedCredibility(event)
  const score = Number(event.credibility_score || 0) || fallback.score
  const level = event.credibility_score ? (event.credibility_level || fallback.level) : fallback.level
  const levelLabel = level === 'HIGH' ? '高' : level === 'LOW' ? '低' : '中'
  return `${Math.round(score)} · ${levelLabel}`
}

function statusLabel(status?: string | null): string {
  const labels: Record<string, string> = {
    OK: '正常',
    READY: '就绪',
    SUCCESS: '成功',
    SKIPPED: '已跳过',
    RUNNING: '运行中',
    STOPPED: '已停止',
    PENDING: '等待中',
    COMPLETED: '已完成',
    QUEUED: '排队中',
    ACTIVE: '已启用',
    FAILED: '失败',
    ERROR: '异常',
    DEGRADED: '降级',
    FALLBACK: '降级结果',
    DISABLED: '已停用',
    UNKNOWN: '未知',
    NO_DATA: '暂无数据',
    HEALTHY: '健康',
    UNSTABLE: '不稳定',
    DOWN: '不可用',
    STALE: '数据过期',
    WARNING: '警告',
    INFO: '信息',
    CRITICAL: '严重',
  }
  return labels[String(status || '').toUpperCase()] || status || '待检查'
}

function riskLabel(level?: string | null): string {
  const labels: Record<string, string> = { HIGH: '高', MEDIUM: '中', LOW: '低' }
  return labels[String(level || 'LOW').toUpperCase()] || level || '低'
}


function displayCredibilityLevel(event: HotspotEvent): string {
  if (Number(event.credibility_score || 0) > 0 && event.credibility_level) return event.credibility_level
  return estimatedCredibility(event).level
}


function hasValidEvidenceUrl(url?: string): boolean {
  if (!url) return false
  try {
    const parsed = new URL(url)
    return ['http:', 'https:'].includes(parsed.protocol) && Boolean(parsed.hostname)
  } catch {
    return false
  }
}


function isFakeSourceItem(item: { source?: string; raw_payload?: Record<string, any> }): boolean {
  return fakeSourceCodes.has(String(item.source || '').toLowerCase()) || Boolean(item.raw_payload?.is_fallback_sample)
}


function hasVerifiableEvidence(event: HotspotEvent): boolean {
  if (event.is_fallback_sample) return false
  return Boolean((event.items || []).some((item) => hasValidEvidenceUrl(item.url) && !isFakeSourceItem(item)))
}


function feedbackButtonKey(event: HotspotEvent, action: EventFeedbackAction): string {
  return `${event.event_key || event.id || event.title}:${action}`
}


function feedbackCount(event: HotspotEvent, action: EventFeedbackAction): number {
  return Number(event.feedback?.counts?.[action] || 0)
}


function feedbackActive(event: HotspotEvent, action: EventFeedbackAction): boolean {
  return feedbackCount(event, action) > 0
}


function applyFeedbackSummary(eventKey: string, summary: HotspotEvent['feedback']) {
  const update = (list: HotspotEvent[]) => {
    const row = list.find((item) => item.event_key === eventKey)
    if (row) {
      row.feedback = summary || {}
      row.score_adjustment = Number(summary?.score_adjustment || 0)
      row.display_heat_score = displayHeatScore(row)
    }
  }
  update(events.value)
  const briefingEvents = todayBriefing.value?.raw_json?.events
  if (Array.isArray(briefingEvents)) update(briefingEvents)
}


function displayHeatScore(event: HotspotEvent): number {
  const base = Number(event.heat_score || 0)
  const adjustment = Number(event.score_adjustment || event.feedback?.score_adjustment || 0)
  if (adjustment) return Math.max(0, Math.min(100, base + adjustment))
  const explicit = Number(event.display_heat_score || 0)
  if (explicit > 0) return Math.max(0, Math.min(100, explicit))
  const adjusted = base + adjustment
  return Math.max(0, Math.min(100, adjusted))
}


async function handleEventFeedback(event: HotspotEvent, action: EventFeedbackAction) {
  if (!event.event_key) {
    setError('这条情报缺少 event_key，无法写入反馈。')
    return
  }
  const key = feedbackButtonKey(event, action)
  feedbackSavingKey.value = key
  try {
    const active = feedbackActive(event, action)
    const result = active ? await deleteEventFeedback(event.event_key, action) : await createEventFeedback(event.event_key, { action })
    applyFeedbackSummary(event.event_key, result.summary)
    if (action === 'BLOCK' && !active) {
      events.value = events.value.filter((item) => item.event_key !== event.event_key)
      const briefingEvents = todayBriefing.value?.raw_json?.events
      if (Array.isArray(briefingEvents)) {
        todayBriefing.value!.raw_json!.events = briefingEvents.filter((item) => item.event_key !== event.event_key)
      }
    }
    const actionLabel = feedbackActions.find((item) => item.value === action)?.label || action
    setMessage(active ? `已撤销“${actionLabel}”反馈` : `已记录“${actionLabel}”反馈，可在左侧“反馈记录”查看和撤销`)
  } catch (error) {
    setError(error)
  } finally {
    feedbackSavingKey.value = ''
  }
}


function sourceHost(url?: string): string {
  if (!url) return ''
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}


function evidenceItems(event: HotspotEvent) {
  const seen = new Set<string>()
  const rawItems = [...(event.items || [])]
    .sort((a, b) => Number(a.rank || 9999) - Number(b.rank || 9999))
    .filter((item) => {
      if (!hasValidEvidenceUrl(item.url) || isFakeSourceItem(item)) return false
      const key = item.url
      if (!key || seen.has(key)) return false
      seen.add(key)
      return true
    })
    .slice(0, 4)
    .map((item) => ({
      key: item.url || `${item.source}:${item.title}`,
      title: shortText(item.title || event.title, 88),
      url: item.url || '',
      sourceName: item.source_name || item.source || '未知来源',
      rankText: item.rank ? `排名 #${item.rank}` : '榜单项',
      hotText: item.raw_hot_score ? ` · 热度 ${item.raw_hot_score}` : '',
      host: sourceHost(item.url),
    }))
  return rawItems
}





function healthClass(level?: string): string {


  if (level === 'HEALTHY') return 'low'


  if (level === 'DOWN' || level === 'UNSTABLE') return 'high'


  return 'medium'


}






function sourceLiveStatus(item?: SourceHealthItem | null): string {


  return statusLabel(item?.live_probe?.status || item?.live_status || item?.health_level || 'UNKNOWN')


}




function sourceLiveMessage(item?: SourceHealthItem | null): string {


  const probe = item?.live_probe


  if (probe?.message) return probe.message


  if (probe?.error) return probe.error


  return item?.latest_error || '-'


}




function relevanceClass(level?: string): string {


  if (level === 'HIGH') return 'low'


  if (level === 'LOW') return 'medium'


  if (level === 'MEDIUM') return 'ai'


  return 'medium'


}





function ragLevelClass(level?: string): string {


  if (level === 'HIGH') return 'low'


  if (level === 'MEDIUM') return 'ai'


  if (level === 'ERROR') return 'high'


  return 'medium'


}





function statusBadgeClass(status?: string): string {


  if (status === 'SUCCESS' || status === 'ACTIVE') return 'low'


  if (status === 'FAILED' || status === 'ERROR') return 'high'


  return 'medium'


}





function formatDateTime(value?: string): string {


  if (!value) return '-'


  const date = dayjs(value)


  return date.isValid() ? date.format('YYYY-MM-DD HH:mm:ss') : value


}






function formatMs(value?: number): string {


  const num = Number(value || 0)


  return num > 0 ? `${Math.round(num)}ms` : '-'


}




function formatPercent(value: number): string {


  const num = Number(value || 0)


  const normalized = num <= 1 ? num * 100 : num


  return `${Math.round(normalized)}%`


}





function formatNumber(value?: number): string {


  const num = Number(value || 0)


  return Number.isInteger(num) ? String(num) : num.toFixed(2)


}

function formatUsd(value?: number): string {
  const cost = Math.max(0, Number(value || 0))
  if (cost < 0.01) return `$${cost.toFixed(6)}`
  return `$${cost.toFixed(2)}`
}





function formatDuration(value?: number): string {


  if (value === undefined || value === null) return '-'


  if (value < 1000) return `${value}ms`


  return `${(value / 1000).toFixed(1)}s`


}

function cleanHistorySummary(text: string): string {
  if (!text) return '无摘要'
  return text
    .replace(/^#+\s*/gm, '')
    .replace(/\*{1,2}([^*]+)\*{1,2}/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .trim()
}

function renderBriefingHtml(markdown: string): string {
  if (!markdown) return ''
  const escapeHtml = (str: string) =>
    str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;')

  const lines = markdown.split(/\r?\n/)
  const out: string[] = []
  let inList = false

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i]
    const trimmed = rawLine.trim()

    if (!trimmed) {
      if (inList) {
        out.push('</ul>')
        inList = false
      }
      continue
    }

    if (trimmed.startsWith('# ')) {
      if (inList) { out.push('</ul>'); inList = false }
      out.push(`<h1>${escapeHtml(trimmed.slice(2).trim())}</h1>`)
      continue
    }
    if (trimmed.startsWith('## ')) {
      if (inList) { out.push('</ul>'); inList = false }
      out.push(`<h2>${escapeHtml(trimmed.slice(3).trim())}</h2>`)
      continue
    }
    if (trimmed.startsWith('### ')) {
      if (inList) { out.push('</ul>'); inList = false }
      out.push(`<h3>${escapeHtml(trimmed.slice(4).trim())}</h3>`)
      continue
    }

    if (/^(\*\*\*|---|___)$/.test(trimmed)) {
      if (inList) { out.push('</ul>'); inList = false }
      out.push('<hr />')
      continue
    }

    const bulletMatch = trimmed.match(/^[-*•]\s+(.*)/)
    const numMatch = trimmed.match(/^(\d+)\.\s+(.*)/)

    if (bulletMatch || numMatch) {
      if (!inList) {
        out.push('<ul>')
        inList = true
      }
      let content = bulletMatch ? bulletMatch[1] : numMatch![2]
      content = escapeHtml(content)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
      if (numMatch) {
        out.push(`<li><strong>${numMatch[1]}.</strong> ${content}</li>`)
      } else {
        out.push(`<li>${content}</li>`)
      }
      continue
    }

    if (inList) {
      out.push('</ul>')
      inList = false
    }

    if (trimmed.startsWith('> ')) {
      const content = escapeHtml(trimmed.slice(2).trim())
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      out.push(`<blockquote>${content}</blockquote>`)
      continue
    }

    let pContent = escapeHtml(trimmed)
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
    out.push(`<p>${pContent}</p>`)
  }

  if (inList) {
    out.push('</ul>')
  }

  return out.join('\n')
}

function providerBrandTag(code: string = '', name: string = ''): { label: string; class: string } {
  const c = `${code} ${name}`.toLowerCase()
  if (c.includes('openai') || c.includes('gpt')) return { label: 'OpenAI 体系', class: 'brand-openai' }
  if (c.includes('gemini') || c.includes('google')) return { label: 'Google Gemini', class: 'brand-gemini' }
  if (c.includes('deepseek')) return { label: 'DeepSeek 深度求索', class: 'brand-deepseek' }
  if (c.includes('anthropic') || c.includes('claude')) return { label: 'Claude 官方', class: 'brand-anthropic' }
  if (c.includes('qwen') || c.includes('dashscope') || c.includes('aliyun') || c.includes('通义')) return { label: '通义千问', class: 'brand-qwen' }
  if (c.includes('zhipu') || c.includes('glm') || c.includes('智谱')) return { label: '智谱 GLM', class: 'brand-zhipu' }
  if (c.includes('moonshot') || c.includes('kimi')) return { label: 'Kimi Moonshot', class: 'brand-kimi' }
  if (c.includes('silicon') || c.includes('硅基流动')) return { label: '硅基流动', class: 'brand-silicon' }
  if (c.includes('ollama') || c.includes('local') || c.includes('本地')) return { label: '本地自建', class: 'brand-local' }
  return { label: '通用通道', class: 'brand-generic' }
}





function shortText(text: string, max = 120): string {


  return !text ? '-' : text.length > max ? `${text.slice(0, max)}...` : text


}





function startGeneratingModal() {


  generating.value = true


  generatingStep.value = 0


  generatingAutoIngest.value = null


  generatingIngestRun.value = null


  if (generatingTimer) window.clearInterval(generatingTimer)


  generatingTimer = window.setInterval(() => {


    if (generatingStep.value < generatingSteps.length - 1) generatingStep.value += 1


  }, 1800)


}





function stopGeneratingModal() {


  if (generatingTimer) {


    window.clearInterval(generatingTimer)


    generatingTimer = undefined


  }


  window.setTimeout(() => {


    generating.value = false


    generatingStep.value = 0


  }, 450)


}





onMounted(() => {
  window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired)
  initializeApp()
})

onBeforeUnmount(() => {
  window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired)
})


</script>





<style scoped>


.app-note {


  padding: 12px 20px;


  margin-top: auto;


  font-size: 12px;


}





.app-note p {


  margin: 6px 0 0;


  color: var(--color-muted);


  line-height: 1.5;


}





.side-stack {


  display: grid;


  gap: 12px;


}





.bar-row {


  display: grid;


  gap: 12px;


}





.bar-row > div:first-child {


  display: flex;


  justify-content: space-between;


  font-size: 12px;


}

.platform-fetch-panel {
  margin-bottom: 16px;
}

.platform-fetch-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.platform-result-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  padding: 0 18px 18px;
}

.platform-result-card {
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-card);
  overflow: hidden;
  transition: var(--transition-smooth);
}

.platform-result-head {
  padding: 14px 16px 10px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-glass);
}

.platform-result-head h3 {
  margin: 0;
  color: var(--color-text);
  font-size: 15px;
  font-weight: 700;
}

.platform-result-head p {
  margin: 4px 0 0;
  color: var(--color-muted);
  font-size: 12px;
}

.mini-note {
  margin-top: 6px !important;
  color: var(--color-muted) !important;
  font-size: 12px !important;
}

.platform-hot-list {
  display: grid;
  gap: 4px;
  padding: 10px;
}

.platform-hot-item {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 9px 12px;
  border-radius: 8px;
  color: var(--color-text);
  text-decoration: none;
  transition: var(--transition-smooth);
}

.platform-hot-item:hover {
  background: var(--color-hover-bg);
}

.platform-rank {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  color: var(--color-primary);
  background: var(--color-primary-light);
  border: 1px solid var(--border-glow);
  font-size: 12px;
  font-weight: 800;
  font-family: var(--font-mono);
}

.platform-title {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 650;
  color: var(--color-text);
}

.platform-title-wrap {
  min-width: 0;
}

.platform-title-wrap small {
  display: inline-block;
  margin-top: 4px;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 700;
}

.platform-hot-item b {
  color: var(--color-muted);
  font-size: 12px;
  font-weight: 700;
  font-family: var(--font-mono);
}

.intelligence-panel {
  overflow: hidden;
  background: var(--surface-card);
}

.intelligence-head {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-glass);
}

.intelligence-head h2 {
  margin: 4px 0 0;
  color: var(--color-text);
  font-size: 19px;
  font-weight: 800;
  letter-spacing: -0.01em;
}

.intelligence-head p {
  margin: 6px 0 0;
  color: var(--color-muted);
  font-size: 12.5px;
  line-height: 1.6;
}

.intelligence-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.ghost-btn.compact {
  min-height: 34px;
  padding: 7px 12px;
  font-size: 12px;
}

.empty-intelligence {
  min-height: 240px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 10px;
  padding: 42px 22px;
  text-align: center;
  color: var(--color-muted);
}

.empty-intelligence svg {
  width: 34px;
  height: 34px;
  color: var(--color-primary);
}

.empty-intelligence b {
  color: var(--color-text);
  font-size: 16px;
}

.empty-intelligence p {
  max-width: 460px;
  margin: 0;
  line-height: 1.7;
}

.intelligence-list {
  display: grid;
  gap: 12px;
  padding: 18px 20px;
}

.intelligence-card {
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-subtle);
  padding: 20px;
  transition: var(--transition-smooth);
}

.intelligence-card:hover {
  border-color: var(--border-hover);
  background: var(--color-hover-bg);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
}

.intel-card-top {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr);
  gap: 14px;
  align-items: flex-start;
}

.intel-rank {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--color-primary);
  background: var(--color-primary-light);
  border: 1px solid var(--border-glow);
  font-size: 13.5px;
  font-weight: 850;
  font-family: var(--font-mono);
}

.intel-card-top h3 {
  margin: 0;
  color: var(--color-text);
  font-size: 16.5px;
  font-weight: 750;
  line-height: 1.45;
  letter-spacing: -0.01em;
}

.intel-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.intel-meta span,
.cred-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 24px;
  padding: 3px 10px;
  border-radius: 6px;
  color: var(--color-muted);
  background: var(--surface-glass);
  border: 1px solid var(--border-subtle);
  font-size: 11.5px;
  font-weight: 650;
}

.intel-meta .favorite-meta {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.3);
}

.favorite-meta svg {
  width: 13px;
  height: 13px;
  fill: currentColor;
}

.cred-pill.high-score {
  color: #10b981;
  background: rgba(16, 185, 129, 0.14);
  border-color: rgba(16, 185, 129, 0.3);
}

.cred-pill.mid-score {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.14);
  border-color: rgba(245, 158, 11, 0.3);
}

.cred-pill.low-score {
  color: #f43f5e;
  background: rgba(244, 63, 94, 0.14);
  border-color: rgba(244, 63, 94, 0.3);
}

.intel-section {
  margin-top: 14px;
  padding-left: 50px;
}

.intel-label {
  display: inline-block;
  margin-bottom: 5px;
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.intel-section p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13.5px;
  line-height: 1.7;
}

.evidence-box {
  margin: 16px 0 0 50px;
  padding: 14px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-glass);
}

.evidence-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 10px;
}

.evidence-head b {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text);
  font-size: 13px;
  font-weight: 700;
}

.evidence-head svg {
  width: 15px;
  height: 15px;
  color: var(--color-primary);
}

.evidence-head span {
  color: var(--color-muted);
  font-size: 11.5px;
}

.evidence-list {
  display: grid;
  gap: 8px;
}

.evidence-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 11px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  color: inherit;
  background: var(--surface-card);
  text-decoration: none;
  transition: var(--transition-smooth);
}

.evidence-item[href]:hover {
  border-color: var(--border-hover);
  background: var(--color-hover-bg);
  box-shadow: 0 0 12px var(--glow-accent);
}

.evidence-item,
.feedback-btn,
.ghost-btn,
.markdown-details summary {
  cursor: pointer;
}

.evidence-item b {
  display: block;
  color: var(--color-text);
  font-size: 12.5px;
  font-weight: 650;
  line-height: 1.45;
}

.evidence-item span {
  display: block;
  margin-top: 4px;
  color: var(--color-muted);
  font-size: 11px;
  line-height: 1.5;
}

.evidence-item svg {
  flex: 0 0 auto;
  width: 16px;
  height: 16px;
  color: var(--color-primary);
}

.intel-footer {
  display: flex;
  gap: 10px;
  align-items: center;
  margin: 14px 0 0 50px;
  color: var(--color-muted);
  font-size: 12px;
}

.intel-feedback {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0 0 50px;
}

.feedback-btn {
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 6px 12px;
  background: var(--surface-card);
  color: var(--color-muted);
  font-size: 12px;
  font-weight: 650;
  transition: var(--transition-smooth);
}

.feedback-btn svg {
  width: 14px;
  height: 14px;
}

.feedback-btn:hover:not(:disabled) {
  border-color: var(--border-glow);
  background: var(--color-hover-bg);
  color: var(--color-text);
}

.feedback-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.feedback-btn.good.active {
  color: #10b981;
  border-color: rgba(16, 185, 129, 0.4);
  background: rgba(16, 185, 129, 0.14);
}

.feedback-btn.bad.active,
.feedback-btn.block.active {
  color: #f43f5e;
  border-color: rgba(244, 63, 94, 0.4);
  background: rgba(244, 63, 94, 0.14);
}

.feedback-btn.star.active {
  color: #f59e0b;
  border-color: rgba(245, 158, 11, 0.4);
  background: rgba(245, 158, 11, 0.14);
}

.feedback-btn.star.active svg {
  fill: currentColor;
}

.intel-risk {
  line-height: 1.5;
}

.markdown-details {
  margin: 0 16px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  overflow: hidden;
  background: var(--surface-subtle);
}

.markdown-details summary {
  padding: 12px 16px;
  cursor: pointer;
  color: var(--color-text);
  font-size: 13px;
  font-weight: 700;
}

.markdown-details .markdown-box {
  max-height: 420px;
  border-top: 1px solid var(--border-subtle);
}

.intelligence-bottom-actions {
  margin: 0 16px 16px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.setup-nudge {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 22px;
  background: var(--surface-card);
  border: 1px solid var(--border-glow);
  border-left: 4px solid var(--color-primary);
  border-radius: 12px;
  margin-bottom: 20px;
  box-shadow: var(--card-shadow);
}

.setup-nudge b {
  display: block;
  font-size: 14.5px;
  font-weight: 750;
  color: var(--color-text);
  margin-bottom: 4px;
}

.setup-nudge p {
  margin: 0;
  font-size: 12.5px;
  color: var(--color-muted);
}

@media (max-width: 900px) {
  .platform-result-grid {
    grid-template-columns: 1fr;
  }

  .intelligence-head {
    flex-direction: column;
  }

  .intel-section,
  .evidence-box,
  .intel-feedback,
  .intel-footer {
    margin-left: 0;
    padding-left: 0;
  }
}

/* ==========================================================================
   Model Provider Edit Modal Overhaul
   ========================================================================== */
.edit-provider-modal {
  width: 740px;
  max-width: 95vw;
  max-height: 88vh;
  padding: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--surface-overlay);
  backdrop-filter: blur(28px);
  border: 1px solid var(--border-glow);
  border-radius: 14px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5), 0 0 35px var(--glow-accent);
}

.edit-provider-modal .chrome-dialog-head {
  padding: 16px 22px;
  margin: 0;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-card);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.modal-badge-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(0, 242, 254, 0.12);
  color: var(--color-primary);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.modal-badge-icon .icon-svg {
  width: 18px;
  height: 18px;
}

.modal-title-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.modal-title-text h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 750;
  color: var(--color-text);
  letter-spacing: normal;
}

.modal-subtitle {
  font-size: 12px;
  color: var(--color-muted);
  letter-spacing: normal !important;
}

.edit-provider-body {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.modal-section {
  background: var(--surface-subtle);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.section-switches {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.toggle-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  background: var(--surface-card);
  border: 1px solid var(--border-subtle);
  color: var(--color-muted);
  user-select: none;
  transition: all 0.2s ease;
}

.toggle-pill input[type="checkbox"] {
  display: none;
}

.pill-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-muted);
  transition: all 0.2s ease;
}

.toggle-pill.checked {
  background: rgba(0, 242, 254, 0.12);
  border-color: rgba(0, 242, 254, 0.35);
  color: var(--color-primary);
}

.toggle-pill.checked .pill-dot {
  background: var(--color-primary);
  box-shadow: 0 0 6px var(--color-primary);
}

.modal-form-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.modal-form-grid-4 {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.modal-form-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.modal-form-item.full-width {
  width: 100%;
}

.item-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text);
}

.item-hint {
  font-size: 11px;
  color: var(--color-muted);
  line-height: 1.35;
}

.modal-input {
  width: 100%;
  min-height: 36px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-card);
  color: var(--color-text);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  letter-spacing: normal !important;
}

.modal-input:focus,
.modal-textarea:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--glow-accent);
}

.modal-input:disabled {
  background: rgba(255, 255, 255, 0.04);
  color: var(--color-muted);
  cursor: not-allowed;
}

.modal-textarea {
  width: 100%;
  padding: 8px 12px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-card);
  color: var(--color-text);
  font-size: 13px;
  line-height: 1.5;
  outline: none;
  resize: vertical;
  transition: border-color 0.2s ease;
}

.input-with-action {
  position: relative;
  display: flex;
  align-items: center;
}

.input-with-action .modal-input {
  padding-right: 36px;
}

.action-btn-inside {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  background: transparent;
  border: none;
  color: var(--color-muted);
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  border-radius: 4px;
  transition: color 0.15s ease;
}

.action-btn-inside:hover {
  color: var(--color-text);
}

.action-btn-inside .btn-icon {
  width: 15px;
  height: 15px;
}

.fetch-btn {
  font-size: 12px;
  padding: 3px 10px;
  min-height: 28px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.fetch-btn .btn-icon {
  width: 13px;
  height: 13px;
}

.model-input-combo {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.model-picker-select {
  width: 100%;
  min-height: 32px;
  padding: 0 10px;
  border-radius: 6px;
  border: 1px dashed var(--border-subtle);
  background: var(--surface-subtle);
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 550;
  outline: none;
  cursor: pointer;
  letter-spacing: normal !important;
}

.quick-models-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 2px;
}

.quick-label {
  font-size: 11px;
  color: var(--color-muted);
}

.quick-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.model-chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--surface-card);
  border: 1px solid var(--border-subtle);
  color: var(--color-muted);
  cursor: pointer;
  transition: all 0.15s ease;
  letter-spacing: normal !important;
}

.model-chip:hover {
  color: var(--color-text);
  border-color: var(--color-primary);
}

.model-chip.active {
  background: rgba(0, 242, 254, 0.12);
  color: var(--color-primary);
  border-color: var(--color-primary);
  font-weight: 600;
}

.modal-foot-custom {
  padding: 14px 22px;
  margin: 0;
  background: var(--surface-card);
  border-top: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  gap: 10px;
}

.test-conn-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.test-conn-btn .btn-icon {
  width: 14px;
  height: 14px;
}

.foot-spacer {
  flex: 1;
}

.save-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.save-btn .btn-icon {
  width: 14px;
  height: 14px;
}

@media (max-width: 680px) {
  .platform-fetch-panel > .panel-head {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .platform-fetch-actions {
    width: 100%;
    min-width: 0;
    justify-content: flex-start;
    flex-wrap: wrap;
  }

  .platform-fetch-actions button {
    max-width: 100%;
    white-space: normal;
  }

  .modal-form-grid-2,
  .modal-form-grid-4 {
    grid-template-columns: 1fr;
  }
}

</style>

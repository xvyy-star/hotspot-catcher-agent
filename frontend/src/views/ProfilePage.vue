<template>
  <section class="profile-container">
    <!-- 顶栏页面标题与快速操作 -->
    <div class="profile-page-header">
      <div class="header-titles">
        <h2 class="page-title">个人中心</h2>
        <p class="page-desc">{{ profile?.display_name }} · {{ roleText }}</p>
      </div>
      <div class="header-actions">
        <button class="ghost-btn small-btn" type="button" :disabled="refreshing" @click="handleRefresh">
          <RefreshCw :class="{ 'spin-icon': refreshing }" class="btn-icon" />
          {{ refreshing ? '刷新中...' : '刷新状态' }}
        </button>
      </div>
    </div>

    <!-- 左右双栏核心布局 -->
    <div class="profile-layout">
      <!-- 左侧：个人名片区 (320px) -->
      <aside class="profile-sidebar-card card">
        <div class="avatar-section">
          <div class="avatar-wrapper">
            <div class="profile-avatar">{{ profile?.avatar_text || 'HA' }}</div>
            <span class="online-indicator" title="当前在线 · 运行中"></span>
          </div>
          <h3 class="profile-name">{{ profile?.display_name || 'Hotspot Admin' }}</h3>
          <div class="profile-handle">@{{ profile?.username || 'admin' }}</div>
          <div class="role-tags">
            <span class="role-badge"><ShieldCheck class="badge-icon" /> {{ roleText }}</span>
            <span class="auth-badge">{{ authModeText }}</span>
          </div>
        </div>

        <div class="sidebar-divider"></div>

        <!-- 关键指标速览 -->
        <div class="quick-status-list">
          <div class="quick-status-item">
            <span class="status-label">客户端 IP</span>
            <span class="status-value font-mono">{{ security?.client_ip || '127.0.0.1' }}</span>
          </div>
          <div class="quick-status-item">
            <span class="status-label">API 鉴权</span>
            <span class="status-value status-pill" :class="profile?.api_auth_enabled ? 'active' : 'inactive'">
              {{ profile?.api_auth_enabled ? '已开启' : '未开启' }}
            </span>
          </div>
          <div class="quick-status-item">
            <span class="status-label">安全健康度</span>
            <span class="status-value health-good">
              <CheckCircle2 class="status-icon" /> {{ (security?.failed_count ?? 0) > 0 ? '需注意' : '良好' }}
            </span>
          </div>
          <div class="quick-status-item">
            <span class="status-label">密码保护</span>
            <span class="status-value">{{ security?.password_hash_configured ? 'BCrypt 加密' : 'SHA256' }}</span>
          </div>
        </div>

        <div class="sidebar-divider"></div>

        <!-- 退出登录按钮 -->
        <div class="sidebar-footer">
          <button class="danger-ghost-btn" type="button" :disabled="loggingOut" @click="showLogoutConfirm = true">
            <LogOut class="btn-icon" />
            {{ loggingOut ? '退出中...' : '退出当前登录' }}
          </button>
        </div>
      </aside>

      <!-- 右侧：Tab 主内容区 -->
      <main class="profile-main-content">
        <!-- Tab 切换导航 -->
        <div class="profile-tabs-nav">
          <button
            v-for="tab in visibleTabs"
            :key="tab.key"
            type="button"
            class="tab-nav-btn"
            :class="{ active: currentTab === tab.key }"
            @click="currentTab = tab.key"
          >
            <component :is="tab.icon" class="tab-icon" />
            <span>{{ tab.label }}</span>
          </button>
        </div>

        <!-- Tab 1: 账号资料与偏好 -->
        <div v-show="currentTab === 'profile'" class="tab-panel">
          <!-- 账号资料卡片 -->
          <div class="card profile-panel">
            <div class="panel-head">
              <div class="panel-head-titles">
                <h4>基本资料</h4>
                <p>管理在情报工作台显示的个人信息与展示名称</p>
              </div>
            </div>

            <form class="clean-form" @submit.prevent="handleSaveProfile">
              <div class="form-grid-2">
                <div class="form-group">
                  <label class="form-label">登录账号</label>
                  <input type="text" :value="profile?.username || 'admin'" disabled class="input-disabled" />
                  <span class="form-hint">账号标识创建后保持不变</span>
                </div>
                <div class="form-group">
                  <label class="form-label">显示昵称</label>
                  <input
                    v-model="displayNameInput"
                    type="text"
                    placeholder="输入显示昵称"
                    maxlength="32"
                    required
                    class="input-control"
                  />
                  <span class="form-hint">将即时同步至系统顶部栏与侧边栏个人信息</span>
                </div>
              </div>

              <div class="form-grid-2">
                <div class="form-group">
                  <label class="form-label">账号角色</label>
                  <input type="text" :value="roleText" disabled class="input-disabled" />
                </div>
                <div class="form-group">
                  <label class="form-label">认证方式</label>
                  <input type="text" :value="authModeText" disabled class="input-disabled" />
                  <span class="form-hint">安全密码独立会话认证</span>
                </div>
              </div>

              <div class="form-actions-right">
                <button class="primary-btn small-btn" type="submit" :disabled="savingProfile">
                  <Check class="btn-icon" />
                  {{ savingProfile ? '保存中...' : '保存资料修改' }}
                </button>
              </div>
            </form>
          </div>

          <!-- 工作台偏好设置卡片 -->
          <div class="card profile-panel">
            <div class="panel-head">
              <div class="panel-head-titles">
                <h4>工作台偏好设置</h4>
                <p>自定义工作台的默认行为、着陆页与数据刷新频率</p>
              </div>
            </div>

            <div class="clean-form">
              <div class="form-grid-2">
                <div class="form-group">
                  <label class="form-label">登录后默认着陆页</label>
                  <select v-model="defaultPagePreference" class="select-control" @change="handleSavePreferences">
                    <option value="dashboard">今日简报 (今日情报重点概览)</option>
                    <option value="events">热点事件池</option>
                    <option v-if="isAdmin" value="dataBoard">数据看板 (系统监控大屏)</option>
                    <option v-if="isAdmin" value="knowledgeQa">智能问答 (专题知识库智能体)</option>
                    <option value="history">简报归档 (历史归档中心)</option>
                  </select>
                  <span class="form-hint">每次登录或进入工作台时，将自动为您打开该模块</span>
                </div>

                <div class="form-group">
                  <label class="form-label">数据自动刷新频率</label>
                  <select v-model="refreshIntervalPreference" class="select-control" @change="handleSavePreferences">
                    <option :value="0">手动刷新 (推荐 · 节约资源)</option>
                    <option :value="30">每 30 秒自动刷新</option>
                    <option :value="60">每 1 分钟自动刷新</option>
                    <option :value="300">每 5 分钟自动刷新</option>
                  </select>
                  <span class="form-hint">控制仪表盘与热点采集状态的后台数据轮询频率</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Tab 2: 登录安全与改密 -->
        <div v-show="currentTab === 'security'" class="tab-panel">
          <!-- 修改密码卡片 -->
          <div class="card profile-panel">
            <div class="panel-head">
              <div class="panel-head-titles">
                <h4>修改登录密码</h4>
                <p>新密码至少 8 位，修改后需重新登录</p>
              </div>
            </div>

            <form class="clean-form" @submit.prevent="handleChangePassword">
              <div class="form-group single-col">
                <label class="form-label">当前原密码</label>
                <div class="input-suffix-wrap">
                  <input
                    v-model="passwordForm.oldPassword"
                    :type="showOldPassword ? 'text' : 'password'"
                    placeholder="请输入当前密码"
                    required
                    class="input-control font-mono"
                  />
                  <button type="button" class="suffix-btn" @click="showOldPassword = !showOldPassword">
                    <component :is="showOldPassword ? EyeOff : Eye" class="suffix-icon" />
                  </button>
                </div>
              </div>

              <div class="form-grid-2">
                <div class="form-group">
                  <label class="form-label">新密码</label>
                  <div class="input-suffix-wrap">
                    <input
                      v-model="passwordForm.newPassword"
                      :type="showNewPassword ? 'text' : 'password'"
                      placeholder="设置新密码 (不少于 8 位)"
                      required
                      minlength="6"
                      class="input-control font-mono"
                    />
                    <button type="button" class="suffix-btn" @click="showNewPassword = !showNewPassword">
                      <component :is="showNewPassword ? EyeOff : Eye" class="suffix-icon" />
                    </button>
                  </div>

                  <!-- 密码强度条 -->
                  <div v-if="passwordForm.newPassword" class="password-strength-bar-wrap">
                    <div class="strength-track">
                      <div class="strength-fill" :class="passwordStrengthClass"></div>
                    </div>
                    <span class="strength-text" :class="passwordStrengthClass">
                      安全强度: {{ passwordStrengthText }}
                    </span>
                  </div>
                </div>

                <div class="form-group">
                  <label class="form-label">确认新密码</label>
                  <div class="input-suffix-wrap">
                    <input
                      v-model="passwordForm.confirmPassword"
                      :type="showNewPassword ? 'text' : 'password'"
                      placeholder="再次输入新密码"
                      required
                      minlength="6"
                      class="input-control font-mono"
                    />
                  </div>
                  <span v-if="passwordMismatch" class="form-error-hint">两次输入的新密码不一致</span>
                </div>
              </div>

              <div class="form-actions-right">
                <button
                  class="primary-btn small-btn"
                  type="submit"
                  :disabled="changingPassword || passwordMismatch || !passwordForm.newPassword"
                >
                  <Lock class="btn-icon" />
                  {{ changingPassword ? '更新中...' : '确认更新密码' }}
                </button>
              </div>
            </form>
          </div>

          <!-- 登录防护与安全状态卡片 -->
          <div class="card profile-panel">
            <div class="panel-head">
              <div class="panel-head-titles">
                <h4>登录防护与安全审计</h4>
                <p>基于 Redis 与系统操作日志的防暴力破解与安全锁定机制</p>
              </div>
            </div>

            <div class="audit-grid">
              <div class="audit-card">
                <div class="audit-title">连续登录失败尝试</div>
                <div class="audit-val">
                  <span class="big-num" :class="{ 'warning-color': (security?.failed_count ?? 0) > 0 }">
                    {{ security?.failed_count ?? 0 }}
                  </span>
                  <span class="max-limit">/ {{ security?.failure_limit || 5 }} 次</span>
                </div>
                <div class="audit-desc">若连续失败达到上限，系统将自动锁定该 IP 900 秒</div>
              </div>

              <div class="audit-card">
                <div class="audit-title">锁定保护状态</div>
                <div class="audit-val status-val">
                  <span v-if="security?.locked_until" class="badge medium">
                    锁定至 {{ formatDateTime(security.locked_until) }}
                  </span>
                  <span v-else class="badge low">正常运行 · 未锁定</span>
                </div>
                <div class="audit-desc">防爆破策略正常运行中，保护系统免受自动化字典攻击</div>
              </div>

              <div class="audit-card">
                <div class="audit-title">最近成功登录时间</div>
                <div class="audit-val text-val font-mono">
                  {{ formatDateTime(security?.last_success_at) }}
                </div>
                <div class="audit-desc">记录上次安全验证通过并签发 Token 的时间</div>
              </div>

              <div class="audit-card">
                <div class="audit-title">上次登录 IP 地址</div>
                <div class="audit-val text-val font-mono">
                  {{ security?.last_success_ip || security?.client_ip || '-' }}
                </div>
                <div class="audit-desc">通过多层可信反向代理精确解析的客户端网络地址</div>
              </div>
            </div>

            <div class="audit-footer-actions">
              <button
                class="ghost-btn small-btn"
                type="button"
                :disabled="resettingFailures"
                @click="handleResetFailures"
              >
                <RefreshCw :class="{ 'spin-icon': resettingFailures }" class="btn-icon" />
                {{ resettingFailures ? '正在重置...' : '重置失败计数与防护状态' }}
              </button>
            </div>
          </div>
        </div>

        <!-- Tab 3: 开发者 API 凭据 -->
        <div v-show="currentTab === 'api'" class="tab-panel">
          <div class="card profile-panel">
            <div class="panel-head">
              <div class="panel-head-titles">
                <h4>API 访问凭据 (Admin Token)</h4>
                <p>供外部自动化运维脚本、CI/CD 流水线或第三方 QQ 机器人调用的授权凭据</p>
              </div>
            </div>

            <div class="token-panel-box">
              <div class="token-title-row">
                <span class="token-label">当前活跃令牌</span>
                <span class="token-type-tag">Bearer Token</span>
              </div>

              <div class="token-input-row">
                <div class="token-value-box font-mono">
                  {{ showTokenFull ? currentToken : maskedToken }}
                </div>
                <div class="token-btn-group">
                  <button class="ghost-btn small-btn" type="button" @click="showTokenFull = !showTokenFull">
                    <component :is="showTokenFull ? EyeOff : Eye" class="btn-icon" />
                    {{ showTokenFull ? '隐藏明文' : '查看完整' }}
                  </button>
                  <button class="primary-btn small-btn" type="button" @click="handleCopyToken">
                    <component :is="tokenCopied ? Check : Copy" class="btn-icon" />
                    {{ tokenCopied ? '已复制！' : '一键复制' }}
                  </button>
                </div>
              </div>

              <p class="token-warning-tip">
                <AlertTriangle class="tip-icon" />
                安全提醒：该令牌具备工作台全部写入与调度权限，切勿泄露或提交至公开 GitHub 仓库。
              </p>
            </div>

            <div class="curl-guide-box">
              <h5 class="guide-title">API 快速调用示例 (CURL)</h5>
              <div class="code-wrapper">
                <pre class="code-block"><code>curl -X GET "http://127.0.0.1:8000/api/hotspots/briefings/today" \
  -H "Authorization: Bearer {{ maskedToken }}" \
  -H "Content-Type: application/json"</code></pre>
              </div>
            </div>
          </div>
        </div>

        <!-- Tab 4: 权限范围清单 -->
        <div v-show="currentTab === 'permissions'" class="tab-panel">
          <div class="card profile-panel">
            <div class="panel-head">
              <div class="panel-head-titles">
                <h4>系统权限范围与能力</h4>
                <p>{{ roleText }}</p>
              </div>
            </div>

            <div class="permission-cards-grid">
              <div v-for="scope in visibleScopes" :key="scope.key" class="permission-scope-card">
                <div class="scope-header">
                  <div class="scope-icon-box"><component :is="scope.icon" /></div>
                  <div class="scope-titles">
                    <h5>{{ scope.title }}</h5>
                    <span class="badge low">已完整授权</span>
                  </div>
                </div>
                <p class="scope-desc">{{ scope.description }}</p>
                <div class="scope-tags-row">
                  <span v-for="tag in scope.tags" :key="tag" class="scope-tag">{{ tag }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>

    <!-- 退出登录二次确认模态弹窗 -->
    <div v-if="showLogoutConfirm" class="modal-overlay" @click.self="showLogoutConfirm = false">
      <div class="modal-card card">
        <div class="modal-head">
          <div class="modal-icon warning"><LogOut /></div>
          <div>
            <h4>确认退出登录？</h4>
            <p>退出后当前浏览器会话将被吊销，再次使用需重新登录。</p>
          </div>
        </div>
        <div class="modal-actions">
          <button class="ghost-btn small-btn" type="button" @click="showLogoutConfirm = false">取消</button>
          <button class="danger-btn small-btn" type="button" :disabled="loggingOut" @click="handleLogout">
            {{ loggingOut ? '退出中...' : '确认退出' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import dayjs from 'dayjs'
import {
  Activity,
  AlertTriangle,
  BookOpen,
  Check,
  CheckCircle2,
  Copy,
  Cpu,
  Eye,
  EyeOff,
  Flame,
  Key,
  Lock,
  LogOut,
  Newspaper,
  RefreshCw,
  ShieldCheck,
  Sliders,
  User,
} from 'lucide-vue-next'

import {
  changeAdminPassword,
  hasAdminAccess,
  clearStoredAdminToken,
  getStoredAdminToken,
  getStoredDefaultPage,
  getStoredRefreshInterval,
  logoutAdmin,
  resetLoginFailures,
  setStoredDefaultPage,
  setStoredRefreshInterval,
  updateUserProfile,
} from '@/api/hotspot'
import type { UserProfile } from '@/types/hotspot'

const props = defineProps<{
  profile: UserProfile | null
}>()

const emit = defineEmits<{
  (e: 'logout'): void
  (e: 'refresh'): void
  (e: 'message', message: string): void
  (e: 'error', error: unknown): void
  (e: 'set-loading', value: boolean): void
}>()

// Tab 配置
type TabKey = 'profile' | 'security' | 'api' | 'permissions'
const currentTab = ref<TabKey>('profile')

const tabs: { key: TabKey; label: string; icon: any }[] = [
  { key: 'profile', label: '资料与偏好', icon: User },
  { key: 'security', label: '安全与改密', icon: Lock },
  { key: 'api', label: '开发者凭据', icon: Key },
  { key: 'permissions', label: '权限清单', icon: ShieldCheck },
]

// 状态控制
const refreshing = ref(false)
const loggingOut = ref(false)
const showLogoutConfirm = ref(false)
const savingProfile = ref(false)
const changingPassword = ref(false)
const resettingFailures = ref(false)
const tokenCopied = ref(false)
const showOldPassword = ref(false)
const showNewPassword = ref(false)
const showTokenFull = ref(false)

// 表单数据
const displayNameInput = ref('')
const defaultPagePreference = ref('dashboard')
const refreshIntervalPreference = ref(0)

const passwordForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

// 计算属性
const security = computed(() => props.profile?.login_security)
const isAdmin = computed(() => hasAdminAccess(props.profile))
const visibleTabs = computed(() => isAdmin.value ? tabs : tabs.filter(tab => tab.key !== 'api'))
const roleText = computed(() => {
  const role = props.profile?.role || 'user'
  if (role === 'owner') return '系统所有者'
  if (role === 'admin') return '系统管理员'
  if (role === 'user') return '普通用户'
  return role
})
const authModeText = computed(() => {
  if (props.profile?.auth_mode === 'admin_token' || props.profile?.auth_mode === 'api_session') return 'API 独立会话'
  if (props.profile?.auth_mode === 'password') return '密码凭据认证'
  return props.profile?.auth_mode || '标准认证'
})

// Token 显示与脱敏
const currentToken = computed(() => getStoredAdminToken())
const maskedToken = computed(() => {
  const t = currentToken.value
  if (!t || t.length < 8) return 'hc_***'
  return `${t.slice(0, 6)}••••••••••••${t.slice(-4)}`
})

// 密码一致性与强度
const passwordMismatch = computed(() => {
  return (
    Boolean(passwordForm.newPassword) &&
    Boolean(passwordForm.confirmPassword) &&
    passwordForm.newPassword !== passwordForm.confirmPassword
  )
})

const passwordStrength = computed(() => {
  const pwd = passwordForm.newPassword
  if (!pwd) return 0
  let score = 0
  if (pwd.length >= 8) score += 1
  if (pwd.length >= 10) score += 1
  if (/[0-9]/.test(pwd) && /[a-zA-Z]/.test(pwd)) score += 1
  if (/[^a-zA-Z0-9]/.test(pwd)) score += 1
  return score
})

const passwordStrengthClass = computed(() => {
  const s = passwordStrength.value
  if (s <= 1) return 'weak'
  if (s <= 2) return 'medium'
  return 'strong'
})

const passwordStrengthText = computed(() => {
  const s = passwordStrength.value
  if (s <= 1) return '弱'
  if (s <= 2) return '中等'
  return '极强'
})

// 权限范围卡片数据
const permissionScopes = [
  {
    key: 'hotspot',
    title: '热点情报采集与运营',
    icon: Flame,
    description: '公开接口采集、热点分类、标签聚类与人工反馈。',
    tags: ['热点事件查看', '源站状态巡检', '清洗策略调优', '反馈标注'],
  },
  {
    key: 'briefing',
    title: '智能早报生成与归档',
    icon: Newspaper,
    description: '异步智能提炼每日早报、AI 大模型润色、历史归档与 QQ 机器人推送。',
    tags: ['今日早报生成', '重新生成润色', '归档下载', 'QQ 机器人推送'],
  },
  {
    key: 'knowledge',
    title: '专业知识库与问答',
    icon: BookOpen,
    description: '知识库文档导入切片、向量 Embedding 检索与多轮 RAG 智能问答。',
    tags: ['文档上传导入', '切片向量检索', '语义问答', '健康状态检测'],
  },
  {
    key: 'system',
    title: '系统运维与模型配置',
    icon: Cpu,
    description: '系统日志实时追踪、全流程运行看板、大模型通道管理与定时调度。',
    tags: ['实时系统日志', '调度规则设定', '模型通道增删改', '全局审计'],
  },
]

const visibleScopes = computed(() => isAdmin.value ? permissionScopes : [{
  key: 'reader', title: '情报阅读与个人反馈', icon: Newspaper,
  description: '今日情报、热点池与简报归档',
  tags: ['阅读情报', '个人收藏', '个人反馈', '个人资料'],
}])

// 初始化
onMounted(() => {
  if (props.profile?.display_name) {
    displayNameInput.value = props.profile.display_name
  }
  defaultPagePreference.value = getStoredDefaultPage()
  if (!isAdmin.value && !['dashboard', 'events', 'history', 'feedbackRecords', 'profile'].includes(defaultPagePreference.value)) defaultPagePreference.value = 'dashboard'
  refreshIntervalPreference.value = getStoredRefreshInterval()
})

// 刷新状态
async function handleRefresh() {
  refreshing.value = true
  try {
    emit('refresh')
    emit('message', '账号与安全状态已刷新')
  } finally {
    setTimeout(() => {
      refreshing.value = false
    }, 400)
  }
}

// 保存资料
async function handleSaveProfile() {
  if (!displayNameInput.value.trim()) return
  savingProfile.value = true
  try {
    const res = await updateUserProfile({ display_name: displayNameInput.value.trim() })
    emit('message', res.message || '个人资料更新成功')
    emit('refresh')
  } catch (err: any) {
    emit('error', err.response?.data?.detail || err.message || '更新资料失败')
  } finally {
    savingProfile.value = false
  }
}

// 保存偏好
function handleSavePreferences() {
  setStoredDefaultPage(defaultPagePreference.value)
  setStoredRefreshInterval(refreshIntervalPreference.value)
  emit('message', '偏好设置已保存')
}

// 修改密码
async function handleChangePassword() {
  if (passwordMismatch.value) return
  if (passwordForm.newPassword.length < 8 || new TextEncoder().encode(passwordForm.newPassword).length > 72) {
    emit('error', '密码至少 8 位，UTF-8 编码长度至多 72 字节。')
    return
  }
  changingPassword.value = true
  try {
    const res = await changeAdminPassword({
      old_password: passwordForm.oldPassword,
      new_password: passwordForm.newPassword,
      confirm_password: passwordForm.confirmPassword,
    })
    emit('message', res.message || '密码修改成功，新密码已生效')
    passwordForm.oldPassword = ''
    passwordForm.newPassword = ''
    passwordForm.confirmPassword = ''
    clearStoredAdminToken()
    emit('logout')
  } catch (err: any) {
    emit('error', err.response?.data?.detail || err.message || '修改密码失败')
  } finally {
    changingPassword.value = false
  }
}

// 重置登录失败
async function handleResetFailures() {
  resettingFailures.value = true
  try {
    const res = await resetLoginFailures()
    emit('message', res.message || '安全防护状态已重置')
    emit('refresh')
  } catch (err: any) {
    emit('error', err.response?.data?.detail || err.message || '重置失败')
  } finally {
    resettingFailures.value = false
  }
}

// 一键复制 Token
async function handleCopyToken() {
  try {
    await navigator.clipboard.writeText(currentToken.value)
    tokenCopied.value = true
    emit('message', 'API 令牌已复制到剪贴板')
    setTimeout(() => {
      tokenCopied.value = false
    }, 2000)
  } catch {
    emit('error', '复制失败，请手动选取复制')
  }
}

// 退出登录
async function handleLogout() {
  loggingOut.value = true
  showLogoutConfirm.value = false
  emit('set-loading', true)
  try {
    await logoutAdmin()
    emit('message', '已退出登录')
  } catch {
    // 服务端异常不阻断本地退出
  } finally {
    clearStoredAdminToken()
    emit('set-loading', false)
    loggingOut.value = false
    emit('logout')
  }
}

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const date = dayjs(value)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm:ss') : value
}
</script>

<style scoped>
.profile-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
}

/* 顶部页头 */
.profile-page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 4px 2px;
}

.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text);
  letter-spacing: normal;
}

.page-desc {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--color-muted);
}

/* 双栏排版 */
.profile-layout {
  display: grid;
  grid-template-columns: 310px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

/* 左侧名片卡 */
.profile-sidebar-card {
  padding: 24px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.avatar-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
}

.avatar-wrapper {
  position: relative;
  margin-bottom: 12px;
}

.profile-avatar {
  width: 64px;
  height: 64px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  color: #ffffff;
  background: var(--brand-gradient);
  font-size: 22px;
  font-weight: 800;
  box-shadow: 0 4px 16px var(--glow-accent);
}

.online-indicator {
  position: absolute;
  bottom: -2px;
  right: -2px;
  width: 14px;
  height: 14px;
  background: #10b981;
  border: 2.5px solid var(--surface-card);
  border-radius: 50%;
}

.profile-name {
  margin: 0 0 4px;
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
}

.profile-handle {
  font-size: 13px;
  color: var(--color-muted);
  margin-bottom: 10px;
}

.role-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: center;
}

.role-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 6px;
  background: rgba(0, 242, 254, 0.12);
  color: var(--color-primary);
  border: 1px solid rgba(0, 242, 254, 0.25);
  font-weight: 600;
}

.auth-badge {
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--surface-subtle);
  color: var(--color-muted);
  border: 1px solid var(--border-subtle);
}

.sidebar-divider {
  width: 100%;
  height: 1px;
  background: var(--border-subtle);
  margin: 18px 0;
}

/* 快速指标列表 */
.quick-status-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.quick-status-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}

.status-label {
  color: var(--color-muted);
}

.status-value {
  color: var(--color-text);
  font-weight: 600;
}

.status-pill {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
}

.status-pill.active {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.health-good {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #10b981;
}

.status-icon {
  width: 14px;
  height: 14px;
}

/* 左侧退出按钮 */
.sidebar-footer {
  width: 100%;
}

.danger-ghost-btn {
  width: 100%;
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 8px;
  background: transparent;
  color: #f43f5e;
  border: 1px solid rgba(244, 63, 94, 0.28);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.danger-ghost-btn:hover:not(:disabled) {
  background: rgba(244, 63, 94, 0.12);
  border-color: #f43f5e;
}

/* 右侧 Tab 区域 */
.profile-main-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.profile-tabs-nav {
  display: flex;
  gap: 6px;
  padding: 4px;
  background: var(--surface-card);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  overflow-x: auto;
}

.tab-nav-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  background: transparent;
  color: var(--color-muted);
  font-size: 13px;
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s ease;
}

.tab-nav-btn:hover {
  color: var(--color-text);
  background: var(--surface-subtle);
}

.tab-nav-btn.active {
  color: var(--color-primary);
  background: var(--surface-subtle);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
}

.tab-icon {
  width: 16px;
  height: 16px;
}

/* 卡片内容 */
.tab-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.profile-panel {
  padding: 20px 22px;
}

.panel-head {
  margin-bottom: 18px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.panel-head-titles h4 {
  margin: 0 0 4px;
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
}

.panel-head-titles p {
  margin: 0;
  font-size: 13px;
  color: var(--color-muted);
}

/* 表单结构 */
.clean-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group.single-col {
  max-width: 50%;
}

.form-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.input-control,
.select-control {
  min-height: 36px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-subtle);
  color: var(--color-text);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s ease;
}

.input-control:focus,
.select-control:focus {
  border-color: var(--color-primary);
}

.input-disabled {
  min-height: 36px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
  background: rgba(255, 255, 255, 0.03);
  color: var(--color-muted);
  font-size: 13px;
  cursor: not-allowed;
}

.form-hint {
  font-size: 12px;
  color: var(--color-muted);
}

.form-error-hint {
  font-size: 12px;
  color: #f43f5e;
}

.form-actions-right {
  display: flex;
  justify-content: flex-end;
  padding-top: 6px;
}

/* 密码输入框与眼睛 */
.input-suffix-wrap {
  position: relative;
  display: flex;
  align-items: center;
}

.input-suffix-wrap input {
  width: 100%;
  padding-right: 36px;
}

.suffix-btn {
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
}

.suffix-btn:hover {
  color: var(--color-text);
}

.suffix-icon {
  width: 16px;
  height: 16px;
}

/* 密码强度条 */
.password-strength-bar-wrap {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.strength-track {
  flex: 1;
  height: 4px;
  background: var(--border-subtle);
  border-radius: 2px;
  overflow: hidden;
}

.strength-fill {
  height: 100%;
  transition: all 0.3s ease;
}

.strength-fill.weak {
  width: 33%;
  background: #f43f5e;
}

.strength-fill.medium {
  width: 66%;
  background: #f59e0b;
}

.strength-fill.strong {
  width: 100%;
  background: #10b981;
}

.strength-text {
  font-size: 11px;
}

.strength-text.weak {
  color: #f43f5e;
}

.strength-text.medium {
  color: #f59e0b;
}

.strength-text.strong {
  color: #10b981;
}

/* 审计卡片网格 */
.audit-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.audit-card {
  padding: 14px;
  border-radius: 8px;
  background: var(--surface-subtle);
  border: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.audit-title {
  font-size: 12px;
  color: var(--color-muted);
}

.audit-val {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.big-num {
  font-size: 20px;
  font-weight: 800;
  color: var(--color-text);
}

.big-num.warning-color {
  color: #f59e0b;
}

.max-limit {
  font-size: 12px;
  color: var(--color-muted);
}

.audit-val.text-val {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.audit-desc {
  font-size: 11px;
  color: var(--color-muted);
  line-height: 1.4;
}

.audit-footer-actions {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}

/* 开发者 API Token 区域 */
.token-panel-box {
  padding: 16px;
  border-radius: 8px;
  background: var(--surface-subtle);
  border: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.token-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.token-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.token-type-tag {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(0, 242, 254, 0.12);
  color: var(--color-primary);
}

.token-input-row {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.token-value-box {
  flex: 1;
  min-width: 200px;
  min-height: 36px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  border-radius: 6px;
  background: var(--surface-card);
  border: 1px solid var(--border-subtle);
  color: var(--color-text);
  font-size: 13px;
  word-break: break-all;
}

.token-btn-group {
  display: flex;
  gap: 8px;
}

.token-warning-tip {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #f59e0b;
}

.tip-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.curl-guide-box {
  margin-top: 18px;
}

.guide-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.code-wrapper {
  background: var(--surface-subtle);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px 14px;
}

.font-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  letter-spacing: normal !important;
}

.code-block {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  color: var(--color-text);
  line-height: 1.6;
  overflow-x: auto;
  letter-spacing: normal !important;
}

/* 权限卡片网格 */
.permission-cards-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.permission-scope-card {
  padding: 16px;
  border-radius: 8px;
  background: var(--surface-subtle);
  border: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.scope-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.scope-icon-box {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: rgba(0, 242, 254, 0.12);
  color: var(--color-primary);
  flex-shrink: 0;
}

.scope-titles {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scope-titles h5 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}

.scope-desc {
  margin: 0;
  font-size: 12px;
  color: var(--color-muted);
  line-height: 1.5;
}

.scope-tags-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.scope-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--surface-card);
  border: 1px solid var(--border-subtle);
  color: var(--color-text);
}

/* 退出确认弹窗 */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  z-index: 9999;
  display: grid;
  place-items: center;
  padding: 16px;
}

.modal-card {
  width: 100%;
  max-width: 420px;
  padding: 24px;
  border-radius: 12px;
}

.modal-head {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  margin-bottom: 20px;
}

.modal-icon.warning {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: rgba(244, 63, 94, 0.12);
  color: #f43f5e;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.modal-head h4 {
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
}

.modal-head p {
  margin: 0;
  font-size: 13px;
  color: var(--color-muted);
  line-height: 1.5;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.btn-icon {
  width: 15px;
  height: 15px;
}

.badge-icon {
  width: 12px;
  height: 12px;
}

.spin-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* 响应式适配 */
@media (max-width: 960px) {
  .profile-layout {
    grid-template-columns: 1fr;
  }

  .form-grid-2,
  .audit-grid,
  .permission-cards-grid {
    grid-template-columns: 1fr;
  }

  .form-group.single-col {
    max-width: 100%;
  }
}
</style>

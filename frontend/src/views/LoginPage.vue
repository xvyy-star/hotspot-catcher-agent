<template>
  <main class="split-login-page" :class="[theme]">
    <!-- 左半屏：轻奢艺术展示空间 (52% 宽度) -->
    <section class="split-left">
      <!-- 柔和慢速光束画布 (自适应黑/白双主题) -->
      <canvas ref="lightCanvasRef" class="ambient-light-canvas"></canvas>
      <div class="paper-grain-overlay"></div>

      <!-- 左顶信息栏 -->
      <header class="left-top-bar" :class="{ 'fade-in': stageSettled }">
        <div class="brand-pill">HOTSPOT CATCHER</div>
        <div class="edition-label">ATELIER · 2026</div>
      </header>

      <!-- 左中央艺术字核心展示区 (居中开场 -> 翻转涌现 -> 丝滑平移至中左) -->
      <div ref="artShowcaseRef" class="art-showcase" :style="showcaseStyle">
        <div class="art-eyebrow" :class="{ 'fade-in': stageSettled }">
          <span>THE INTELLIGENCE DISCOVERY</span>
        </div>

        <!-- 第一行：HOTSPOT 艺术字体 (Italiana + Playfair Display) -->
        <div class="art-title-mask">
          <div class="art-title-row">
            <span 
              v-for="(char, idx) in titleChars" 
              :key="idx" 
              class="art-char"
              :class="{ 
                'italic-flair': char.isAccent,
                'revealed': lettersRevealed 
              }"
              :style="{ animationDelay: `${0.1 + idx * 0.065}s` }"
            >
              {{ char.letter }}
            </span>
          </div>
        </div>

        <!-- 第二行：Catcher 手写艺术衬线字 -->
        <div class="art-subline-mask">
          <div class="art-subline-row" :class="{ 'revealed': lettersRevealed }">
            <span class="script-title">Catcher</span>
            <span class="atelier-tag">科技情报工作台</span>
          </div>
        </div>
      </div>

      <!-- 左底哲思格言 -->
      <footer class="left-bottom-bar" :class="{ 'fade-in': stageSettled }">
        <p class="manifesto-quote">“博观而约取，厚积而薄发。”</p>
        <span class="manifesto-sub">全网科技热点多维捕获 · 知识脉络深度研判</span>
      </footer>
    </section>

    <!-- 右半屏：经典、正常、极简高级的日常登录屏 (48% 宽度) -->
    <section class="split-right">
      <!-- 右上角主题切换 -->
      <ThemeToggle variant="floating" />

      <!-- 登录表单卡片 (随字母位移同时温和滑入显现) -->
      <div 
        ref="loginCardRef" 
        class="login-card-container" 
        :class="{ 'card-revealed': stageSettled }"
      >
        <header class="card-head">
          <span class="head-eyebrow">COMMAND ACCESS</span>
          <h1 class="head-title">{{ registering ? '新席位注册' : '账号登录' }}</h1>
          <p class="head-desc">{{ registering ? '创建您的专属观测账号以接入情报系统' : '请输入您的账号与密码进入情报控制台' }}</p>
        </header>

        <!-- 登录 / 注册 Tab 切换 (若系统开启注册) -->
        <div v-if="registrationEnabled" class="auth-tabs-row" role="tablist">
          <button 
            type="button" 
            role="tab"
            class="tab-item" 
            :class="{ active: !registering }" 
            :disabled="submitting" 
            @click="switchMode(false)"
          >
            账号登录
          </button>
          <button 
            type="button" 
            role="tab"
            class="tab-item" 
            :class="{ active: registering }" 
            :disabled="submitting" 
            @click="switchMode(true)"
          >
            新席位注册
          </button>
        </div>

        <!-- 表单 -->
        <form class="normal-auth-form" @submit.prevent="handleSubmit">
          <!-- 账号 -->
          <div class="form-field">
            <label for="usernameField">{{ registering ? '注册账号' : '账号' }}</label>
            <div class="input-shell">
              <input
                id="usernameField"
                v-model.trim="form.username"
                autocomplete="username"
                :placeholder="registering ? '3-32位字母/数字/下划线' : '请输入账号'"
                :maxlength="registering ? 32 : 64"
                required
              />
            </div>
          </div>

          <!-- 注册时的昵称 -->
          <div v-if="registering" class="form-field">
            <label for="displayNameField">用户昵称</label>
            <div class="input-shell">
              <input
                id="displayNameField"
                v-model.trim="form.displayName"
                autocomplete="nickname"
                placeholder="请输入显示昵称"
                maxlength="32"
                required
              />
            </div>
          </div>

          <!-- 密码 -->
          <div class="form-field">
            <label for="passwordField">{{ registering ? '设置密码' : '密码' }}</label>
            <div class="input-shell">
              <input
                id="passwordField"
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                :autocomplete="registering ? 'new-password' : 'current-password'"
                placeholder="请输入密码"
                required
              />
              <button 
                type="button" 
                class="pwd-toggle" 
                :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                @click="showPassword = !showPassword"
              >
                <EyeOff v-if="showPassword" class="icon-eye" />
                <Eye v-else class="icon-eye" />
              </button>
            </div>
          </div>

          <!-- 注册时确认密码 -->
          <div v-if="registering" class="form-field">
            <label for="confirmPwdField">确认密码</label>
            <div class="input-shell">
              <input
                id="confirmPwdField"
                v-model="form.confirmPassword"
                type="password"
                autocomplete="new-password"
                placeholder="请再次输入密码"
                required
              />
            </div>
          </div>

          <!-- 选项栏 -->
          <div v-if="!registering" class="form-options">
            <label class="remember-label">
              <input v-model="form.remember" type="checkbox" />
              <span>保持 30 天免登录</span>
            </label>
            <span class="forgot-tip" @click="handleForgotPrompt">忘记密码？</span>
          </div>

          <!-- 经典高品质主按钮 -->
          <button class="primary-submit-btn" type="submit" :disabled="submitting">
            <RefreshCw v-if="submitting" class="spin-loader" />
            <UserPlus v-else-if="registering" class="btn-icon" />
            <LogIn v-else class="btn-icon" />
            <span>{{ submitting ? '验证提交中...' : registering ? '注册并进入工作台' : '进入工作台' }}</span>
          </button>
        </form>

        <footer class="card-footer-info">
          Hotspot Catcher Agent · 科技情报中枢系统 © 2026
        </footer>
      </div>
    </section>

    <!-- 顶部轻量浮动消息提示弹窗 (Toast) -->
    <Teleport to="body">
      <Transition name="toast-slide">
        <div 
          v-if="toast.visible" 
          class="auth-toast-bubble"
          :class="toast.type"
          role="alert"
          aria-live="assertive"
        >
          <div class="toast-icon-wrap">
            <AlertCircle v-if="toast.type === 'error'" class="toast-status-icon" />
            <CheckCircle2 v-else-if="toast.type === 'success'" class="toast-status-icon" />
            <Info v-else class="toast-status-icon" />
          </div>
          <span class="toast-content">{{ toast.message }}</span>
          <button 
            type="button" 
            class="toast-dismiss-btn" 
            aria-label="关闭提示" 
            @click="toast.visible = false"
          >
            <X class="toast-close-icon" />
          </button>
        </div>
      </Transition>
    </Teleport>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { AlertCircle, CheckCircle2, Eye, EyeOff, Info, LogIn, RefreshCw, UserPlus, X } from 'lucide-vue-next'

import ThemeToggle from '@/components/ThemeToggle.vue'
import { useTheme } from '@/composables/useTheme'
import { getRegistrationOptions, loginAdmin, registerUser, setStoredAdminToken } from '@/api/hotspot'
import type { AuthLoginResult } from '@/types/hotspot'

const emit = defineEmits<{
  'login-success': [result: AuthLoginResult]
  'error': [error: unknown]
  'set-loading': [value: boolean]
}>()

const { theme } = useTheme()

const form = reactive({
  username: '',
  displayName: '',
  password: '',
  confirmPassword: '',
  remember: true,
})

const submitting = ref(false)
const registering = ref(false)
const registrationEnabled = ref(false)
const showPassword = ref(false)

// 浮动弹窗提示 (Toast) 状态
const toast = reactive({
  visible: false,
  message: '',
  type: 'error' as 'error' | 'success' | 'info',
})

let toastTimer: number | null = null

function showToast(message: string, type: 'error' | 'success' | 'info' = 'error', duration = 3800) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.message = message
  toast.type = type
  toast.visible = true
  toastTimer = window.setTimeout(() => {
    toast.visible = false
  }, duration)
}

// 艺术字母定义
const titleChars = [
  { letter: 'H', isAccent: false },
  { letter: 'O', isAccent: false },
  { letter: 'T', isAccent: false },
  { letter: 'S', isAccent: true }, // S: Playfair Display 艺术倾斜流线
  { letter: 'P', isAccent: false },
  { letter: 'O', isAccent: false },
  { letter: 'T', isAccent: false },
]

// =========================================================================
// 核心入场动效逻辑：居中从容翻转涌现 -> 停顿聚焦 -> 温和优雅平移至中左 -> 右侧卡片舒缓滑入
// =========================================================================
const artShowcaseRef = ref<HTMLElement | null>(null)
const loginCardRef = ref<HTMLElement | null>(null)

const lettersRevealed = ref(false)
const stageSettled = ref(false)
const showcaseOffsetX = ref(0)
const isTransitioning = ref(false)

// 调缓位移过渡曲线至 1.7s，温和渐慢无突兀感
const showcaseStyle = computed(() => {
  return {
    transform: `translateX(${showcaseOffsetX.value}px)`,
    transition: isTransitioning.value ? 'transform 1.7s cubic-bezier(0.22, 1, 0.36, 1)' : 'none',
  }
})

let timerStep1: number | null = null
let timerStep2: number | null = null

function triggerEntranceSequence() {
  if (timerStep1) clearTimeout(timerStep1)
  if (timerStep2) clearTimeout(timerStep2)

  // 1. 状态重置
  lettersRevealed.value = false
  stageSettled.value = false
  isTransitioning.value = false

  nextTick(() => {
    const showcase = artShowcaseRef.value
    if (!showcase) return

    // 仅在桌面宽屏执行居中至中左位移动效
    const isDesktop = window.innerWidth > 960
    if (isDesktop) {
      const screenCenterX = window.innerWidth / 2
      const showcaseRect = showcase.getBoundingClientRect()
      // 计算使整个艺术字块精准处于屏幕水平中央所需的位移量
      const currentCenterX = showcaseRect.left + showcaseRect.width / 2
      showcaseOffsetX.value = screenCenterX - currentCenterX
    } else {
      showcaseOffsetX.value = 0
    }

    // 步骤 1：触发字母在屏幕中央 3D 翻转温和升起
    timerStep1 = window.setTimeout(() => {
      lettersRevealed.value = true

      // 步骤 2：在正中央停留约 0.85 秒让用户充分感知，随后温和从容平移至中左并舒展卡片
      timerStep2 = window.setTimeout(() => {
        isTransitioning.value = true
        showcaseOffsetX.value = 0
        stageSettled.value = true
      }, 850)
    }, 150)
  })
}

// =========================================================================
// 左侧自然慢速柔光画布（自适应浅色暖白 / 深色黑金双主题）
// =========================================================================
const lightCanvasRef = ref<HTMLCanvasElement | null>(null)
let animFrameId: number | null = null
let canvasTime = 0

function runCanvasAnimation() {
  const canvas = lightCanvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const parent = canvas.parentElement
  if (parent) {
    if (canvas.width !== parent.offsetWidth || canvas.height !== parent.offsetHeight) {
      canvas.width = parent.offsetWidth
      canvas.height = parent.offsetHeight
    }
  }

  canvasTime += 0.002
  const w = canvas.width
  const h = canvas.height

  ctx.clearRect(0, 0, w, h)

  const isDark = theme.value === 'dark'

  if (isDark) {
    // 深邃黑曜奢华底色与暖金微光
    ctx.fillStyle = '#0c0d12'
    ctx.fillRect(0, 0, w, h)

    ctx.save()
    ctx.filter = 'blur(90px)'

    // 奢华香槟金与微紫琥珀光斑
    const l1X = w * 0.45 + Math.sin(canvasTime) * 60
    const l1Y = h * 0.4 + Math.cos(canvasTime * 0.8) * 50
    ctx.beginPath()
    ctx.arc(l1X, l1Y, w * 0.38, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(212, 175, 55, 0.12)' // 哑光金
    ctx.fill()

    const l2X = w * 0.7 + Math.cos(canvasTime * 1.1) * 50
    const l2Y = h * 0.65 + Math.sin(canvasTime * 0.9) * 40
    ctx.beginPath()
    ctx.arc(l2X, l2Y, w * 0.32, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(120, 80, 180, 0.08)' // 极深邃暗紫
    ctx.fill()

    ctx.restore()
  } else {
    // 浅色暖白画廊底色与自然采光
    ctx.fillStyle = '#f6f4ee'
    ctx.fillRect(0, 0, w, h)

    ctx.save()
    ctx.filter = 'blur(80px)'

    const l1X = w * 0.45 + Math.sin(canvasTime) * 60
    const l1Y = h * 0.4 + Math.cos(canvasTime * 0.8) * 50
    ctx.beginPath()
    ctx.arc(l1X, l1Y, w * 0.35, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(255, 255, 255, 0.65)'
    ctx.fill()

    const l2X = w * 0.7 + Math.cos(canvasTime * 1.1) * 50
    const l2Y = h * 0.65 + Math.sin(canvasTime * 0.9) * 40
    ctx.beginPath()
    ctx.arc(l2X, l2Y, w * 0.3, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(218, 204, 185, 0.28)'
    ctx.fill()

    ctx.restore()
  }

  animFrameId = requestAnimationFrame(runCanvasAnimation)
}

onMounted(async () => {
  runCanvasAnimation()
  triggerEntranceSequence()

  try {
    registrationEnabled.value = (await getRegistrationOptions()).registration_enabled === true
  } catch {
    showToast('注册状态读取失败，请刷新页面重试。', 'error')
  }
})

onUnmounted(() => {
  if (animFrameId) {
    cancelAnimationFrame(animFrameId)
    animFrameId = null
  }
  if (timerStep1) clearTimeout(timerStep1)
  if (timerStep2) clearTimeout(timerStep2)
  if (toastTimer) clearTimeout(toastTimer)
})

function switchMode(value: boolean) {
  registering.value = value
  form.password = ''
  form.confirmPassword = ''
  toast.visible = false
}

function handleForgotPrompt() {
  showToast('如需重置密码，请联系系统管理员通过控制台安全指令处理。', 'info', 4500)
}

async function handleSubmit() {
  if (registering.value) {
    if (!/^[a-z0-9_.-]{3,32}$/.test(form.username.toLowerCase())) {
      showToast('账号需为 3 至 32 位英文字母、数字、下划线、点或短横线。', 'error')
      return
    }
    if (form.password.length < 8 || new TextEncoder().encode(form.password).length > 72) {
      showToast('密码需至少 8 位，UTF-8 编码长度至多 72 字节。', 'error')
      return
    }
    if (form.password !== form.confirmPassword) {
      showToast('两次输入的密码不一致。', 'error')
      return
    }
  }

  submitting.value = true
  emit('set-loading', true)
  try {
    if (registering.value) {
      await registerUser({
        username: form.username.toLowerCase(),
        display_name: form.displayName,
        password: form.password,
        confirm_password: form.confirmPassword,
      })
      switchMode(false)
      showToast('席位创建成功，请使用新账号登录。', 'success')
    } else {
      const result = await loginAdmin({
        username: form.username,
        password: form.password,
        remember: form.remember,
      })
      setStoredAdminToken(result.token)
      emit('login-success', result)
    }
  } catch (error: any) {
    const detail = error.response?.data?.detail
    showToast(typeof detail === 'string' ? detail : error.message || '请求失败，请稍后重试。', 'error')
  } finally {
    submitting.value = false
    emit('set-loading', false)
  }
}
</script>

<style scoped>
/* =========================================================================
   分屏轻奢高阶排版系统 (Quiet Luxury Split Layout - 双主题完全覆盖)
   ========================================================================= */
.split-login-page {
  display: flex;
  width: 100vw;
  min-height: 100vh;
  background-color: #ffffff;
  color: #18181b;
  font-family: var(--font-sans);
  overflow-x: hidden;
  position: relative;
  transition: background-color 0.4s ease, color 0.4s ease;
}

.split-login-page.dark {
  background-color: #ffffff;
}

/* -------------------------------------------------------------------------
   左屏艺术画卷 (52% 宽度)
   ------------------------------------------------------------------------- */
.split-left {
  position: relative;
  flex: 0 0 52%;
  min-height: 100vh;
  background-color: #f6f4ee;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 56px 64px 48px;
  overflow: hidden;
  border-right: 1px solid rgba(0, 0, 0, 0.06);
  user-select: none;
  transition: background-color 0.4s ease, border-color 0.4s ease;
}

.split-login-page.dark .split-left {
  background-color: #0c0d12;
  border-right-color: rgba(255, 255, 255, 0.07);
}

.ambient-light-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
}

.paper-grain-overlay {
  position: absolute;
  inset: 0;
  z-index: 2;
  opacity: 0.035;
  pointer-events: none;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
}

/* 左顶信息 */
.left-top-bar {
  position: relative;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  opacity: 0;
  transform: translateY(-8px);
  transition: opacity 0.8s ease, transform 0.8s ease;
}

.left-top-bar.fade-in {
  opacity: 1;
  transform: translateY(0);
}

.brand-pill {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 2.5px;
  color: #8c7355;
  text-transform: uppercase;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.split-login-page.dark .brand-pill {
  color: #d4af37;
}

.brand-pill::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #8c7355;
  opacity: 0.8;
}

.split-login-page.dark .brand-pill::before {
  background: #d4af37;
  box-shadow: 0 0 8px rgba(212, 175, 55, 0.7);
}

.edition-label {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 1.5px;
  color: #a1a1aa;
}

.split-login-page.dark .edition-label {
  color: #71717a;
}

/* 艺术字展示区 */
.art-showcase {
  position: relative;
  z-index: 10;
  margin: auto 0;
  padding: 24px 0;
  will-change: transform;
}

.art-eyebrow {
  font-family: var(--font-mono);
  font-size: 11.5px;
  letter-spacing: 4px;
  color: #71717a;
  text-transform: uppercase;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 12px;
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 0.8s ease, transform 0.8s ease;
}

.split-login-page.dark .art-eyebrow {
  color: #a1a1aa;
}

.art-eyebrow.fade-in {
  opacity: 1;
  transform: translateY(0);
}

.art-eyebrow::after {
  content: '';
  display: inline-block;
  width: 40px;
  height: 1px;
  background: rgba(0, 0, 0, 0.15);
}

.split-login-page.dark .art-eyebrow::after {
  background: rgba(255, 255, 255, 0.15);
}

.art-title-mask {
  overflow: hidden;
  margin-bottom: 12px;
}

.art-title-row {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.art-char {
  font-family: 'Italiana', serif;
  font-size: clamp(60px, 6vw, 92px);
  line-height: 0.95;
  color: #18181b;
  display: inline-block;
  letter-spacing: 0.04em;
  transform: translateY(120%) rotateX(-60deg);
  opacity: 0;
  will-change: transform, opacity;
  transition: color 0.3s ease;
}

.split-login-page.dark .art-char {
  color: #f3f4f6;
  text-shadow: 0 4px 20px rgba(0, 0, 0, 0.6);
}

.art-char.italic-flair {
  font-family: 'Playfair Display', serif;
  font-style: italic;
  font-weight: 400;
  color: #8c7355;
  margin: 0 2px;
}

.split-login-page.dark .art-char.italic-flair {
  color: #d4af37;
  filter: drop-shadow(0 2px 10px rgba(212, 175, 55, 0.35));
}

.art-char.revealed {
  animation: slideUpChar 1.35s cubic-bezier(0.22, 1, 0.36, 1) forwards;
}

.art-subline-mask {
  overflow: hidden;
  margin-top: 6px;
}

.art-subline-row {
  display: flex;
  align-items: baseline;
  gap: 16px;
  transform: translateY(120%);
  opacity: 0;
  will-change: transform, opacity;
}

.art-subline-row.revealed {
  animation: slideUpSub 1.25s cubic-bezier(0.22, 1, 0.36, 1) 0.35s forwards;
}

.script-title {
  font-family: 'Playfair Display', serif;
  font-style: italic;
  font-size: clamp(32px, 3.2vw, 48px);
  font-weight: 400;
  color: #8c7355;
  letter-spacing: 0.02em;
  transition: color 0.3s ease;
}

.split-login-page.dark .script-title {
  color: #d4af37;
}

.atelier-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 3px;
  color: #71717a;
  text-transform: uppercase;
}

.split-login-page.dark .atelier-tag {
  color: #8e8e93;
}

/* 左底哲思 */
.left-bottom-bar {
  position: relative;
  z-index: 10;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  padding-top: 24px;
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 0.8s ease, transform 0.8s ease, border-color 0.4s ease;
}

.split-login-page.dark .left-bottom-bar {
  border-top-color: rgba(255, 255, 255, 0.08);
}

.left-bottom-bar.fade-in {
  opacity: 1;
  transform: translateY(0);
}

.manifesto-quote {
  font-family: 'Playfair Display', serif;
  font-style: italic;
  font-size: 14.5px;
  line-height: 1.6;
  color: #71717a;
  margin-bottom: 6px;
}

.split-login-page.dark .manifesto-quote {
  color: #a1a1aa;
}

.manifesto-sub {
  font-size: 12px;
  color: #a1a1aa;
  letter-spacing: 1px;
}

.split-login-page.dark .manifesto-sub {
  color: #71717a;
}

/* -------------------------------------------------------------------------
   右屏标准登录卡片 (48% 宽度：无论黑白主题均保持纯净白底高阶质感)
   ------------------------------------------------------------------------- */
.split-right {
  flex: 0 0 48%;
  min-height: 100vh;
  background-color: #ffffff !important;
  color: #18181b !important;
  color-scheme: light !important;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: 48px 56px;
  position: relative;
}

/* 卡片容器 */
.login-card-container {
  width: 100%;
  max-width: 380px;
  opacity: 0;
  transform: translateX(35px);
  transition: opacity 1.6s cubic-bezier(0.22, 1, 0.36, 1), transform 1.6s cubic-bezier(0.22, 1, 0.36, 1);
  will-change: transform, opacity;
}

.login-card-container.card-revealed {
  opacity: 1;
  transform: translateX(0);
}

.card-head {
  margin-bottom: 28px;
}

.head-eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 2px;
  color: #8c7355;
  text-transform: uppercase;
  font-weight: 600;
  margin-bottom: 8px;
  display: block;
}

.head-title {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #18181b;
  margin-bottom: 8px;
}

.head-desc {
  font-size: 13px;
  color: #71717a;
  line-height: 1.5;
}

/* Tabs */
.auth-tabs-row {
  display: flex;
  border-bottom: 1px solid #e4e4e7;
  margin-bottom: 24px;
}

.tab-item {
  padding: 10px 20px 10px 0;
  font-size: 13.5px;
  font-weight: 500;
  color: #71717a;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tab-item.active {
  color: #18181b;
  font-weight: 600;
  border-bottom-color: #18181b;
}

/* -------------------------------------------------------------------------
   浮动轻量弹窗提醒 (Auth Toast Bubble)
   ------------------------------------------------------------------------- */
.auth-toast-bubble {
  position: fixed;
  top: 28px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10000;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 18px;
  border-radius: 9999px;
  background: #ffffff !important;
  color: #18181b !important;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.4;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.12), 0 2px 8px rgba(0, 0, 0, 0.05) !important;
  border: 1px solid rgba(0, 0, 0, 0.08) !important;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  pointer-events: auto;
  max-width: 90vw;
  user-select: none;
}

.auth-toast-bubble.error {
  border-color: rgba(239, 68, 68, 0.3) !important;
  color: #991b1b !important;
}

.auth-toast-bubble.error .toast-status-icon {
  color: #ef4444;
}

.auth-toast-bubble.success {
  border-color: rgba(16, 185, 129, 0.3) !important;
  color: #065f46 !important;
}

.auth-toast-bubble.success .toast-status-icon {
  color: #10b981;
}

.auth-toast-bubble.info {
  border-color: rgba(99, 102, 241, 0.3) !important;
  color: #3730a3 !important;
}

.auth-toast-bubble.info .toast-status-icon {
  color: #6366f1;
}

.toast-icon-wrap {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.toast-status-icon {
  width: 16px;
  height: 16px;
}

.toast-content {
  font-family: var(--font-sans);
  letter-spacing: -0.01em;
}

.toast-dismiss-btn {
  background: none;
  border: none;
  padding: 3px;
  margin-left: 4px;
  color: #9ca3af;
  cursor: pointer;
  display: flex;
  align-items: center;
  border-radius: 50%;
  transition: all 0.15s ease;
}

.toast-dismiss-btn:hover {
  color: #4b5563;
  background: rgba(0, 0, 0, 0.06);
}

.toast-close-icon {
  width: 14px;
  height: 14px;
}

.toast-slide-enter-active,
.toast-slide-leave-active {
  transition: all 0.32s cubic-bezier(0.16, 1, 0.3, 1);
}

.toast-slide-enter-from {
  opacity: 0;
  transform: translate(-50%, -18px) scale(0.96);
}

.toast-slide-leave-to {
  opacity: 0;
  transform: translate(-50%, -12px) scale(0.96);
}

/* 表单字段 */
.normal-auth-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.form-field label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #18181b;
  margin-bottom: 7px;
}

.input-shell {
  position: relative;
  display: flex;
  align-items: center;
  background: #ffffff !important;
  border: 1px solid #e4e4e7 !important;
  border-radius: 8px;
  transition: all 0.2s ease;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04) !important;
  overflow: hidden;
}

.input-shell:focus-within {
  border-color: #18181b !important;
  box-shadow: 0 0 0 1px #18181b !important;
  outline: none !important;
}

.input-shell input {
  width: 100%;
  height: 44px;
  padding: 0 14px;
  border: none !important;
  background: #ffffff !important;
  outline: none !important;
  box-shadow: none !important;
  font-size: 13.5px;
  color: #18181b !important;
  font-family: var(--font-sans);
  color-scheme: light !important;
}

.input-shell input:focus,
.input-shell input:focus-visible {
  outline: none !important;
  box-shadow: none !important;
  border: none !important;
}

.input-shell input::placeholder {
  color: #a1a1aa !important;
  font-size: 13px;
}

.input-shell input:-webkit-autofill,
.input-shell input:-webkit-autofill:hover, 
.input-shell input:-webkit-autofill:focus {
  -webkit-text-fill-color: #18181b !important;
  -webkit-box-shadow: 0 0 0px 1000px #ffffff inset !important;
  box-shadow: 0 0 0px 1000px #ffffff inset !important;
  transition: background-color 5000s ease-in-out 0s;
}

.pwd-toggle {
  background: #ffffff !important;
  border: none !important;
  padding: 0 12px;
  color: #71717a !important;
  cursor: pointer;
  display: flex;
  align-items: center;
  transition: color 0.2s ease;
  height: 44px;
}

.pwd-toggle:hover {
  color: #18181b !important;
}

.icon-eye {
  width: 17px;
  height: 17px;
}

/* 选项行 */
.form-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: -2px 0 6px;
  font-size: 12.5px;
  color: #71717a;
}

.remember-label {
  display: flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
  user-select: none;
}

.remember-label input {
  accent-color: #18181b;
  width: 15px;
  height: 15px;
  cursor: pointer;
}

.forgot-tip {
  color: #71717a;
  cursor: pointer;
  transition: color 0.2s ease;
}

.forgot-tip:hover {
  color: #18181b;
  text-decoration: underline;
}

/* 登录主按钮 */
.primary-submit-btn {
  width: 100%;
  height: 44px;
  background: #18181b;
  color: #ffffff;
  border: none;
  border-radius: 8px;
  font-family: var(--font-sans);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: 0.5px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
  margin-top: 4px;
}

.primary-submit-btn:hover:not(:disabled) {
  background: #27272a;
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.16);
}

.primary-submit-btn:active:not(:disabled) {
  transform: translateY(0);
}

.primary-submit-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.btn-icon {
  width: 16px;
  height: 16px;
}

.spin-loader {
  width: 16px;
  height: 16px;
  animation: spin 0.7s linear infinite;
}

.card-footer-info {
  margin-top: 28px;
  text-align: center;
  font-size: 11.5px;
  color: #a1a1aa;
}

/* 关键帧 */
@keyframes slideUpChar {
  0% {
    transform: translateY(120%) rotateX(-60deg);
    opacity: 0;
  }
  100% {
    transform: translateY(0%) rotateX(0deg);
    opacity: 1;
  }
}

@keyframes slideUpSub {
  0% {
    transform: translateY(120%);
    opacity: 0;
  }
  100% {
    transform: translateY(0%);
    opacity: 1;
  }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 响应式断点 */
@media (max-width: 960px) {
  .split-login-page {
    flex-direction: column;
  }
  .split-left {
    flex: none;
    width: 100%;
    min-height: auto;
    padding: 48px 32px;
  }
  .split-right {
    flex: none;
    width: 100%;
    min-height: auto;
    padding: 56px 32px 64px;
  }
  .top-actions-bar {
    top: 20px;
    right: 24px;
  }
}
</style>

<template>
  <main class="login-page">
    <div class="login-ambient-mesh">
      <div class="glow-orb orb-1"></div>
      <div class="glow-orb orb-2"></div>
    </div>

    <!-- Theme Toggle at Bottom-Left -->
    <ThemeToggle variant="floating" />

    <div class="login-shell">
      <header class="login-brand">
        <div class="login-brand-mark">
          <ShieldCheck />
        </div>
        <div>
          <strong>热点捕手</strong>
          <span>AI 科技情报 Agent · 工作台</span>
        </div>
      </header>

      <section class="login-card" aria-labelledby="login-title">
        <div class="login-card-head">
          <span class="eyebrow">COMMAND CONSOLE</span>
          <h1 id="login-title">管理员身份认证</h1>
          <p>请输入安全凭据以进入情报决策中枢。</p>
        </div>

        <form class="login-form" @submit.prevent="handleSubmit">
          <label class="form-item">
            <span>管理员账号</span>
            <div class="input-wrap">
              <input v-model.trim="form.username" autocomplete="username" placeholder="请输入管理员账号（默认 admin）" />
            </div>
          </label>

          <label class="form-item">
            <span>管理员密码</span>
            <div class="input-wrap">
              <input
                v-model.trim="form.password"
                autocomplete="current-password"
                type="password"
                placeholder="请输入管理员密码"
              />
            </div>
          </label>

          <label class="remember-row">
            <input v-model="form.remember" type="checkbox" />
            <span>保持当前浏览器登录状态 (30天)</span>
          </label>

          <button class="primary-btn login-submit" type="submit" :disabled="submitting">
            <RefreshCw v-if="submitting" class="spinning" />
            <LogIn v-else />
            {{ submitting ? '验证中...' : '进入情报中枢' }}
          </button>
        </form>
      </section>

      <footer class="login-footer">
        <span>Hotspot Catcher Agent</span>
        <span class="dot-sep">·</span>
        <span>AI 与计算机技术情报</span>
      </footer>
    </div>
  </main>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { LogIn, RefreshCw, ShieldCheck } from 'lucide-vue-next'

import ThemeToggle from '@/components/ThemeToggle.vue'
import { loginAdmin, setStoredAdminToken } from '@/api/hotspot'
import type { AuthLoginResult } from '@/types/hotspot'

const emit = defineEmits<{
  (e: 'login-success', result: AuthLoginResult): void
  (e: 'error', error: unknown): void
  (e: 'set-loading', value: boolean): void
}>()

const form = reactive({
  username: 'admin',
  password: '',
  remember: true,
})

const submitting = ref(false)

async function handleSubmit() {
  if (!form.username) {
    emit('error', new Error('请输入管理员账号'))
    return
  }
  if (!form.password) {
    emit('error', new Error('请输入管理员密码'))
    return
  }
  submitting.value = true
  emit('set-loading', true)
  try {
    const result = await loginAdmin({
      username: form.username,
      password: form.password,
      remember: form.remember,
    })
    setStoredAdminToken(result.token)
    emit('login-success', result)
  } catch (error) {
    emit('error', error)
  } finally {
    submitting.value = false
    emit('set-loading', false)
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px 16px;
  background: var(--bg-page-gradient);
  position: relative;
  overflow: hidden;
  font-family: var(--font-sans);
}

.login-ambient-mesh {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
  z-index: 0;
}

.glow-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.45;
  animation: pulse-glow 8s ease-in-out infinite alternate;
}

.orb-1 {
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, rgba(0, 242, 254, 0.35) 0%, rgba(99, 102, 241, 0.15) 70%, transparent 100%);
  top: -120px;
  left: -120px;
}

.orb-2 {
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.35) 0%, rgba(168, 85, 247, 0.15) 70%, transparent 100%);
  bottom: -150px;
  right: -150px;
  animation-delay: -4s;
}

@keyframes pulse-glow {
  0% { transform: scale(0.9) translate(0, 0); opacity: 0.35; }
  100% { transform: scale(1.15) translate(30px, 20px); opacity: 0.55; }
}

.login-shell {
  width: min(100%, 420px);
  position: relative;
  z-index: 10;
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 22px;
}

.login-brand-mark {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  color: #ffffff;
  background: var(--brand-gradient);
  box-shadow: 0 4px 18px var(--glow-accent);
}

.login-brand-mark svg {
  width: 24px;
  height: 24px;
}

.login-brand strong {
  display: block;
  color: var(--color-text);
  font-size: 19px;
  font-weight: 800;
  letter-spacing: -0.01em;
}

.login-brand span {
  display: block;
  margin-top: 3px;
  color: var(--color-muted);
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
}

.login-card {
  width: 100%;
  padding: 32px 30px;
  border: 1px solid var(--border-glow);
  border-radius: 16px;
  background: var(--surface-card);
  backdrop-filter: blur(28px);
  -webkit-backdrop-filter: blur(28px);
  box-shadow: var(--card-shadow), 0 0 24px var(--glow-accent);
  position: relative;
}

.login-card::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--brand-gradient);
  border-radius: 16px 16px 0 0;
}

.login-card-head {
  margin-bottom: 24px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--border-subtle);
}

.eyebrow {
  display: inline-block;
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.05em;
}

.login-card h1 {
  margin: 4px 0 0;
  color: var(--color-text);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.login-card-head p {
  margin: 6px 0 0;
  color: var(--color-muted);
  font-size: 13px;
  line-height: 1.5;
}

.login-form {
  display: grid;
  gap: 18px;
}

.form-item {
  display: grid;
  gap: 6px;
  text-align: left;
}

.form-item span {
  color: var(--color-muted);
  font-size: 12px;
  font-weight: 600;
}

.input-wrap input {
  width: 100%;
  height: 44px;
  background: var(--surface-glass);
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  padding: 0 14px;
  color: var(--color-text);
  font-size: 14px;
  outline: none;
  box-sizing: border-box;
  transition: var(--transition-smooth);
}

.input-wrap input::placeholder {
  color: var(--color-muted);
  opacity: 0.6;
}

.input-wrap input:focus {
  border-color: var(--color-primary);
  background: var(--color-card);
  box-shadow: 0 0 0 3px var(--glow-accent);
}

.remember-row {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--color-muted);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
}

.remember-row input {
  width: 16px;
  height: 16px;
  accent-color: var(--color-primary);
  cursor: pointer;
}

.login-submit {
  width: 100%;
  height: 46px;
  margin-top: 4px;
  font-size: 14.5px;
}

.login-footer {
  margin: 22px 0 0;
  color: var(--color-muted);
  font-size: 11.5px;
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  opacity: 0.85;
}

.dot-sep {
  opacity: 0.5;
}
</style>

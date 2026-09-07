<template>
  <button
    type="button"
    class="theme-toggle-btn"
    :class="[variant, { collapsed }]"
    :title="theme === 'dark' ? '切换为浅色主题' : '切换为黑色主题'"
    :aria-label="theme === 'dark' ? '切换为浅色主题' : '切换为黑色主题'"
    @click="toggleTheme"
  >
    <div class="icon-wrapper">
      <Sun v-if="theme === 'dark'" class="theme-icon sun" />
      <Moon v-else class="theme-icon moon" />
    </div>
    <span v-if="!collapsed && variant !== 'sidebar'" class="theme-label">
      {{ theme === 'dark' ? '浅色' : '黑色' }}
    </span>
  </button>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { Sun, Moon } from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'

withDefaults(
  defineProps<{
    variant?: 'sidebar' | 'floating'
    collapsed?: boolean
  }>(),
  {
    variant: 'sidebar',
    collapsed: false,
  }
)

const { theme, toggleTheme, initTheme } = useTheme()

onMounted(() => {
  initTheme()
})
</script>

<style scoped>
.theme-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border-radius: 8px;
  cursor: pointer;
  outline: none;
  font-family: var(--font-sans, inherit);
  font-size: 12px;
  font-weight: 600;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  user-select: none;
  box-sizing: border-box;
}

.icon-wrapper {
  display: grid;
  place-items: center;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.theme-toggle-btn:hover .icon-wrapper {
  transform: rotate(18deg) scale(1.1);
}

.theme-icon {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
}

.theme-icon.sun {
  color: #fbbf24;
  filter: drop-shadow(0 0 5px rgba(251, 191, 36, 0.5));
}

.theme-icon.moon {
  color: #6366f1;
  filter: drop-shadow(0 0 5px rgba(99, 102, 241, 0.5));
}

/* Sidebar variant */
.theme-toggle-btn.sidebar {
  padding: 0;
  width: 36px;
  height: 36px;
  background: var(--color-hover-bg);
  border: 1px solid var(--border-subtle);
  color: var(--color-muted);
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.theme-toggle-btn.sidebar:hover {
  background: var(--color-active-bg);
  border-color: var(--border-glow);
  color: var(--color-primary);
}

.theme-toggle-btn.sidebar.collapsed {
  width: 36px;
  height: 36px;
  padding: 0;
  justify-content: center;
}

/* Floating variant for Login */
.theme-toggle-btn.floating {
  position: fixed;
  right: 28px;
  top: 28px;
  left: auto;
  bottom: auto;
  z-index: 999;
  padding: 7px 16px;
  border-radius: 9999px;
  background: #ffffff !important;
  border: 1px solid rgba(0, 0, 0, 0.08) !important;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.03) !important;
  color: #18181b !important;
  cursor: pointer;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.theme-toggle-btn.floating .theme-label {
  color: #18181b !important;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.theme-toggle-btn.floating:hover {
  transform: translateY(-1.5px);
  background: #ffffff !important;
  border-color: rgba(0, 0, 0, 0.16) !important;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08), 0 2px 4px rgba(0, 0, 0, 0.04) !important;
  color: #18181b !important;
}

.theme-toggle-btn.floating:active {
  transform: translateY(0);
}

.theme-label {
  white-space: nowrap;
}
</style>

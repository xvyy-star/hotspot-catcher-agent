<template>
  <button
    type="button"
    class="theme-toggle-btn"
    :class="[variant, { collapsed }]"
    :title="theme === 'dark' ? '切换为浅色极光主题' : '切换为深邃黑曜石主题'"
    :aria-label="theme === 'dark' ? '切换为浅色极光主题' : '切换为深邃黑曜石主题'"
    @click="toggleTheme"
  >
    <div class="icon-wrapper">
      <Sun v-if="theme === 'dark'" class="theme-icon sun" />
      <Moon v-else class="theme-icon moon" />
    </div>
    <span v-if="!collapsed" class="theme-label">
      {{ theme === 'dark' ? '浅色极光' : '深邃黑曜' }}
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
  padding: 6px 10px;
  background: var(--surface-subtle, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  color: var(--color-text);
  height: 34px;
}

.theme-toggle-btn.sidebar:hover {
  background: var(--color-hover-bg);
  border-color: var(--border-glow, rgba(0, 242, 254, 0.3));
  color: var(--color-primary);
}

.theme-toggle-btn.sidebar.collapsed {
  width: 34px;
  height: 34px;
  padding: 0;
  justify-content: center;
}

/* Floating variant for Login */
.theme-toggle-btn.floating {
  position: fixed;
  left: 24px;
  bottom: 24px;
  z-index: 999;
  padding: 8px 16px;
  border-radius: 9999px;
  background: var(--surface-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--border-glow);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
  color: var(--color-text);
}

.theme-toggle-btn.floating:hover {
  transform: translateY(-2px);
  border-color: var(--color-primary);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.3), 0 0 15px var(--glow-accent);
}

.theme-label {
  white-space: nowrap;
}
</style>

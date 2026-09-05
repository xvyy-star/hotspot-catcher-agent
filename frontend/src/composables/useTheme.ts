import { ref } from 'vue'

export type AppTheme = 'dark' | 'light'

const STORAGE_KEY = 'HOTSPOT_THEME'

const currentTheme = ref<AppTheme>('dark')

export function useTheme() {
  function initTheme() {
    const saved = localStorage.getItem(STORAGE_KEY) as AppTheme | null
    const theme = saved === 'light' ? 'light' : 'dark'
    setTheme(theme)
  }

  function setTheme(theme: AppTheme) {
    currentTheme.value = theme
    localStorage.setItem(STORAGE_KEY, theme)
    document.documentElement.setAttribute('data-theme', theme)
  }

  function toggleTheme() {
    const next = currentTheme.value === 'dark' ? 'light' : 'dark'
    setTheme(next)
  }

  return {
    theme: currentTheme,
    initTheme,
    setTheme,
    toggleTheme,
  }
}

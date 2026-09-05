import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './style.css'
import App from './App.vue'

// Discard pre-cutover answers that may quote removed source material.
try {
  localStorage.removeItem('HOTSPOT_KNOWLEDGE_QA_CHAT_V1')
} catch {
  // Storage may be disabled; application startup must still work.
}

createApp(App).use(ElementPlus).mount('#app')

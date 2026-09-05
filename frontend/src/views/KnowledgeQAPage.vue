<template>
  <div class="qa-page">
    <!-- Compact Top Document & Model Status Card -->
    <section class="qa-doc-card card">
      <div class="qa-doc-head">
        <div class="qa-title-wrap">
          <div class="qa-icon"><Bot /></div>
          <div class="qa-title-text">
            <div class="qa-title-main">
              <h2>知识问答助手</h2>
              <span :class="['qa-status-pill', qaModelStatus.tone]">{{ qaModelStatus.label }}</span>
            </div>
            <p class="qa-subtitle">
              <span class="qa-scope-badge">
                {{ selectedDocIds.length ? `已选 ${selectedDocIds.length} 个特定文档` : '全局知识库' }}
              </span>
              <span class="qa-model-hint">{{ qaModelStatus.desc }}</span>
            </p>
          </div>
        </div>
        <div class="qa-head-actions">
          <button
            class="ghost-btn small-btn"
            type="button"
            :class="{ active: !docsCollapsed }"
            @click="docsCollapsed = !docsCollapsed"
          >
            <BookOpen /> {{ docsCollapsed ? '筛选文档' : '收起文档' }}
            <span v-if="selectedDocIds.length" class="qa-badge-count">{{ selectedDocIds.length }}</span>
          </button>
          <button class="ghost-btn small-btn" type="button" :disabled="busy" @click="clearChat">
            清空对话
          </button>
        </div>
      </div>

      <!-- Expandable Document Selector Drawer -->
      <div v-show="!docsCollapsed" class="qa-doc-drawer">
        <div class="qa-drawer-toolbar">
          <label class="qa-select-all">
            <input type="checkbox" :checked="allReadySelected" :disabled="!readyDocs.length" @change="toggleSelectAll" />
            <span>全选所有已就绪文档</span>
            <em>（共 {{ readyDocs.length }} 个可用文档）</em>
          </label>
          <span v-if="selectedDocIds.length" class="qa-drawer-stat">已勾选 {{ selectedDocIds.length }} 个文档进行针对性问答</span>
        </div>
        <div v-if="readyDocs.length" class="qa-doc-grid">
          <label v-for="doc in readyDocs" :key="doc.id" :class="['qa-doc-item', { selected: selectedDocIds.includes(doc.id) }]">
            <input v-model="selectedDocIds" type="checkbox" :value="doc.id" />
            <div class="qa-doc-info">
              <b>{{ doc.title }}</b>
              <em>{{ doc.source || '手动导入' }} · {{ doc.chunk_count }} 个分块</em>
            </div>
          </label>
        </div>
        <p v-else class="empty-hint">暂无已索引文档，请先到“知识库 RAG”页面上传或导入早报。</p>
      </div>
    </section>

    <!-- Main Chat Card -->
    <section class="qa-chat-card card">
      <div ref="chatBodyRef" class="qa-chat-body">
        <!-- Modern Welcome Hero (Empty State) -->
        <div v-if="messages.length <= 1" class="qa-empty-hero">
          <div class="qa-hero-badge">
            <Sparkles />
          </div>
          <h3 class="qa-hero-title">智能知识库问答助手</h3>
          <p class="qa-hero-desc">
            基于 RAG 检索增强技术，精准检索已索引的历史早报与情报文档，为您提供深度归纳与事实溯源。
          </p>
          <div class="qa-hero-suggestions">
            <div class="qa-suggestions-label">推荐快捷提问：</div>
            <div class="qa-preset-grid">
              <button
                v-for="prompt in presetPrompts"
                :key="prompt"
                class="qa-preset-card"
                type="button"
                :disabled="busy"
                @click="applyPresetPrompt(prompt)"
              >
                <span class="qa-preset-bullet">✦</span>
                <span class="qa-preset-text">{{ prompt }}</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Chat Messages -->
        <div v-for="msg in messages" :key="msg.id" :class="['qa-message-row', msg.role]">
          <div class="qa-avatar" :aria-label="msg.role === 'assistant' ? '问答助手' : '当前用户'">
            <Bot v-if="msg.role === 'assistant'" />
            <UserRound v-else />
          </div>
          <div class="qa-bubble">
            <div class="qa-bubble-content">{{ msg.content }}</div>
            <div v-if="msg.references?.length" class="qa-references">
              <div class="qa-ref-title">
                <span>📚 溯源引用材料 ({{ msg.references.length }})：</span>
              </div>
              <div class="qa-ref-list">
                <button
                  v-for="ref in msg.references"
                  :key="`${msg.id}-${ref.document_id}-${ref.chunk_id}`"
                  class="qa-ref-chip"
                  type="button"
                  :title="`点击复制引用内容：\n${ref.content}`"
                  @click="copyText(ref.content)"
                >
                  <span class="qa-ref-doc">{{ ref.document_title }} #{{ ref.chunk_index }}</span>
                  <em class="qa-ref-score">相关度 {{ formatNumber(ref.score) }}</em>
                </button>
              </div>
            </div>
            <div v-if="displayMode(msg)" class="qa-mode">
              {{ displayMode(msg) }}{{ msg.model ? ` · ${msg.model}` : '' }}
            </div>
          </div>
        </div>

        <div v-if="busy && !streaming" class="qa-message-row assistant">
          <div class="qa-avatar" aria-label="问答助手"><Bot /></div>
          <div class="qa-bubble typing">
            <Clock3 /> {{ pendingHint }}
          </div>
        </div>
      </div>

      <!-- Pinned Input Panel -->
      <div class="qa-input-panel">
        <div class="qa-meta-row">
          <div class="qa-meta-left">
            <label for="qa-top-k">检索引用数 (Top-K)</label>
            <input id="qa-top-k" v-model.number="topK" class="qa-topk" type="number" min="1" max="20" />
          </div>
          <span class="qa-input-tip">按 Enter 发送，Shift + Enter 换行</span>
        </div>
        <div class="qa-input-row">
          <textarea
            v-model="question"
            :disabled="busy"
            rows="2"
            placeholder="输入您想基于知识库检索的问题，例如：总结近期关于 DeepSeek 的关键评测与行业影响..."
            @keydown.enter.exact.prevent="handleAsk"
          />
          <button class="qa-send-btn" type="button" :disabled="busy || !question.trim()" title="发送问题" @click="handleAsk">
            <Send />
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { Bot, BookOpen, Clock3, Send, UserRound, Sparkles } from 'lucide-vue-next'
import { askKnowledgeStream, listKnowledgeDocuments, listModelProviders } from '@/api/hotspot'
import type { AIModelProvider, KnowledgeDocument, KnowledgeSearchResult } from '@/types/hotspot'

type ChatRole = 'assistant' | 'user'

interface ChatMessage {
  id: number
  role: ChatRole
  content: string
  references?: KnowledgeSearchResult[]
  mode?: string
  model?: string
}

const CHAT_STORAGE_KEY = 'HOTSPOT_KNOWLEDGE_QA_CHAT_V2'
const MAX_PERSISTED_MESSAGES = 80

const presetPrompts = [
  '总结近期核心 AI 与算力模型动态',
  '分析近期大模型商业化落地与产业竞争态势',
  '梳理关于 DeepSeek 的技术评测与社区讨论',
  '近一周有哪些高热度开源项目与突围技术？',
]

function createWelcomeMessage(): ChatMessage {
  return {
    id: 1,
    role: 'assistant',
    content: '知识库问答已就绪。你可以直接提问，或选择快捷问题开启检索。',
  }
}

function loadStoredMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(CHAT_STORAGE_KEY)
    if (!raw) return [createWelcomeMessage()]
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return [createWelcomeMessage()]
    const rows = parsed
      .filter((item) => item && (item.role === 'assistant' || item.role === 'user') && typeof item.content === 'string')
      .slice(-MAX_PERSISTED_MESSAGES)
      .map((item, index) => ({
        id: Number(item.id) || index + 1,
        role: item.role as ChatRole,
        content: item.content,
        references: Array.isArray(item.references) ? item.references : [],
        mode: typeof item.mode === 'string' ? item.mode : undefined,
        model: typeof item.model === 'string' ? item.model : undefined,
      }))
    return rows.length ? rows : [createWelcomeMessage()]
  } catch {
    return [createWelcomeMessage()]
  }
}

const emit = defineEmits<{
  (e: 'message', text: string): void
  (e: 'error', err: any): void
  (e: 'set-loading', loading: boolean): void
}>()

const docs = ref<KnowledgeDocument[]>([])
const modelProviders = ref<AIModelProvider[]>([])
const selectedDocIds = ref<number[]>([])
const docsCollapsed = ref(true)
const messages = ref<ChatMessage[]>(loadStoredMessages())
const question = ref('')
const topK = ref(5)
const busy = ref(false)
const streaming = ref(false)
const pendingHint = ref('正在处理你的问题...')
const chatBodyRef = ref<HTMLElement | null>(null)
let messageSeed = Math.max(1, ...messages.value.map((msg) => Number(msg.id) || 1))
let persistTimer: number | undefined

function persistMessagesNow() {
  try {
    const payload = messages.value.slice(-MAX_PERSISTED_MESSAGES)
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(payload))
  } catch {
    // localStorage 满了或被禁用时，不影响问答主流程。
  }
}

function schedulePersistMessages() {
  if (persistTimer) window.clearTimeout(persistTimer)
  persistTimer = window.setTimeout(() => {
    persistMessagesNow()
    persistTimer = undefined
  }, 300)
}

watch(messages, schedulePersistMessages, { deep: true })

function applyPresetPrompt(promptText: string) {
  question.value = promptText
  handleAsk()
}

function displayMode(msg: ChatMessage): string {
  if (!msg.mode || msg.mode === 'DIRECT_REPLY') return ''
  if (msg.mode === 'LLM_RAG') return '知识库回答'
  if (msg.mode === 'RULE_RAG') return '规则摘要'
  if (msg.mode === 'NO_CONTEXT') return '未检索到资料'
  return msg.mode
}

const readyDocs = computed(() => docs.value.filter((doc) => doc.status === 'READY' || doc.chunk_count > 0))
const selectedDocs = computed(() => readyDocs.value.filter((doc) => selectedDocIds.value.includes(doc.id)))
const allReadySelected = computed(() => readyDocs.value.length > 0 && selectedDocIds.value.length === readyDocs.value.length)
const enabledProviders = computed(() => modelProviders.value.filter((provider) => provider.enabled))
const usableProviders = computed(() => enabledProviders.value.filter((provider) => !provider.requires_api_key || provider.api_key_configured))
const qaModelStatus = computed(() => {
  if (usableProviders.value.length) {
    const provider = usableProviders.value[0]
    const keyHint = provider.uses_env_api_key ? '，Key 来自后端 .env' : provider.api_key_configured ? '，Key 已配置' : ''
    return {
      label: '模型就绪',
      tone: 'ok',
      desc: `优先调用 ${provider.name || provider.code} / ${provider.model}${keyHint}`,
    }
  }
  if (enabledProviders.value.length) {
    return {
      label: '规则摘要',
      tone: 'warn',
      desc: '当前有启用通道但未配置 API Key，将使用本地规则摘要',
    }
  }
  return {
    label: '未配模型',
    tone: 'warn',
    desc: '当前未启用模型，可在“模型通道配置”开启通道',
  }
})

async function refresh() {
  emit('set-loading', true)
  busy.value = true
  try {
    const [docRows, providerRows] = await Promise.allSettled([
      listKnowledgeDocuments(200),
      listModelProviders(),
    ])
    if (docRows.status === 'fulfilled') docs.value = docRows.value
    if (providerRows.status === 'fulfilled') modelProviders.value = providerRows.value
    selectedDocIds.value = selectedDocIds.value.filter((id) => readyDocs.value.some((doc) => doc.id === id))
  } catch (error) {
    emit('error', error)
  } finally {
    busy.value = false
    emit('set-loading', false)
  }
}

function toggleSelectAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  selectedDocIds.value = checked ? readyDocs.value.map((doc) => doc.id) : []
}

function clearChat() {
  if (persistTimer) {
    window.clearTimeout(persistTimer)
    persistTimer = undefined
  }
  localStorage.removeItem(CHAT_STORAGE_KEY)
  messages.value = [
    {
      id: ++messageSeed,
      role: 'assistant',
      content: '对话已清空。你可以继续基于知识库提问。',
    },
  ]
  question.value = ''
  persistMessagesNow()
}

function buildScopedQuestion(rawQuestion: string): string {
  const history = messages.value
    .slice(-6)
    .map((msg) => `${msg.role === 'user' ? '用户' : '助手'}：${msg.content}`)
    .join('\n')

  const scope = selectedDocs.value.length
    ? `本次用户选择的参考文档如下，请优先围绕这些文档回答；如果引用到其他知识库材料，请明确说明：\n${selectedDocs.value
        .map((doc) => `- document_id=${doc.id}，标题=${doc.title}，来源=${doc.source || 'manual'}`)
        .join('\n')}`
    : '本次用户未限定文档范围，请基于全部知识库检索回答。'

  return `${scope}\n\n最近对话：\n${history || '无'}\n\n用户新问题：${rawQuestion}`
}

async function handleAsk() {
  const rawQuestion = question.value.trim()
  if (!rawQuestion) return

  messages.value.push({ id: ++messageSeed, role: 'user', content: rawQuestion })
  question.value = ''
  await scrollToBottom()

  pendingHint.value = '正在检索知识库并生成回答...'
  busy.value = true
  streaming.value = true
  emit('set-loading', true)
  const assistantId = ++messageSeed
  messages.value.push({
    id: assistantId,
    role: 'assistant',
    content: '',
    references: [],
  })
  const updateAssistant = (updater: (msg: ChatMessage) => void) => {
    const msg = messages.value.find((item) => item.id === assistantId)
    if (msg) updater(msg)
  }
  try {
    await askKnowledgeStream(
      buildScopedQuestion(rawQuestion),
      topK.value,
      selectedDocs.value.map((doc) => doc.id),
      (event) => {
        if (event.type === 'meta') {
          updateAssistant((msg) => {
            msg.mode = event.mode
            msg.model = event.model
            msg.references = event.references || []
          })
        } else if (event.type === 'delta' && event.content) {
          updateAssistant((msg) => {
            msg.content += event.content
          })
          void scrollToBottom()
        } else if (event.type === 'error') {
          throw new Error(event.message || event.error || '流式问答失败')
        }
      },
    )
    updateAssistant((msg) => {
      if (!msg.content.trim()) msg.content = '没有生成有效回答。'
    })
    await scrollToBottom()
  } catch (error) {
    emit('error', error)
    updateAssistant((msg) => {
      msg.content = msg.content || '知识库问答失败，请稍后重试，或先确认知识库已有可检索文档。'
    })
  } finally {
    streaming.value = false
    busy.value = false
    emit('set-loading', false)
    await scrollToBottom()
  }
}

async function scrollToBottom() {
  await nextTick()
  const el = chatBodyRef.value
  if (el) el.scrollTop = el.scrollHeight
}

async function copyText(text: string) {
  if (!text) return
  await navigator.clipboard.writeText(text)
  emit('message', '引用内容已复制到剪贴板')
}

function formatNumber(value?: number): string {
  const num = Number(value || 0)
  return Number.isInteger(num) ? String(num) : num.toFixed(3)
}

onMounted(refresh)

defineExpose({
  refresh,
})
</script>

<style scoped>
.qa-page {
  width: min(1200px, 100%);
  margin: 0 auto;
  height: calc(100vh - 126px);
  min-height: 540px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
}

.qa-doc-card {
  flex-shrink: 0;
  border-radius: 12px;
  border: 1px solid var(--border-card);
  background: var(--color-card);
  backdrop-filter: blur(20px);
  overflow: hidden;
  transition: var(--transition-smooth);
}

.qa-doc-head {
  min-height: 52px;
  padding: 10px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.qa-title-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.qa-icon {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--color-primary);
  background: var(--color-primary-light);
  flex-shrink: 0;
}

.qa-icon svg,
.qa-head-actions svg,
.qa-send-btn svg {
  width: 17px;
  height: 17px;
}

.qa-title-text {
  min-width: 0;
}

.qa-title-main {
  display: flex;
  align-items: center;
  gap: 10px;
}

.qa-title-main h2 {
  margin: 0;
  color: var(--color-text);
  font-size: 15px;
  font-weight: 700;
}

.qa-subtitle {
  margin: 2px 0 0;
  color: var(--color-muted);
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.qa-scope-badge {
  color: var(--color-primary);
  font-weight: 600;
}

.qa-model-hint {
  color: var(--color-muted);
}

.qa-status-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
}

.qa-status-pill.ok {
  color: #059669;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.qa-status-pill.warn {
  color: #d97706;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.25);
}

.qa-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.qa-head-actions .ghost-btn.active {
  color: var(--color-primary);
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.qa-badge-count {
  background: var(--color-primary);
  color: #fff;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
  margin-left: 2px;
  font-weight: 700;
}

/* Expandable Drawer */
.qa-doc-drawer {
  padding: 12px 18px 14px;
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-subtle);
  max-height: 190px;
  overflow-y: auto;
}

.qa-drawer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.qa-select-all {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.qa-select-all em {
  color: var(--color-muted);
  font-style: normal;
  font-weight: 400;
}

.qa-drawer-stat {
  font-size: 12px;
  color: var(--color-primary);
  font-weight: 600;
}

.qa-doc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 8px;
}

.qa-doc-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-card);
  cursor: pointer;
  transition: var(--transition-smooth);
}

.qa-doc-item:hover {
  border-color: var(--border-hover);
  background: var(--color-hover-bg);
}

.qa-doc-item.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.qa-doc-item input {
  margin-top: 3px;
  cursor: pointer;
}

.qa-doc-info {
  min-width: 0;
  flex: 1;
}

.qa-doc-info b {
  display: block;
  font-size: 12px;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
}

.qa-doc-info em {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: var(--color-muted);
  font-style: normal;
}

/* Chat Card */
.qa-chat-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: 12px;
  border: 1px solid var(--border-card);
  background: var(--color-card);
  backdrop-filter: blur(20px);
}

.qa-chat-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px;
  background: var(--surface-card);
}

/* Modern Welcome Hero */
.qa-empty-hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 32px 16px 20px;
  margin: 12px 0 24px;
}

.qa-hero-badge {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--color-primary), #6366f1);
  color: #fff;
  display: grid;
  place-items: center;
  margin-bottom: 14px;
  box-shadow: 0 4px 16px var(--glow-accent);
}

.qa-hero-badge svg {
  width: 24px;
  height: 24px;
}

.qa-hero-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text);
}

.qa-hero-desc {
  margin: 8px 0 20px;
  max-width: 520px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-muted);
}

.qa-hero-suggestions {
  width: 100%;
  max-width: 680px;
  text-align: left;
}

.qa-suggestions-label {
  font-size: 12px;
  color: var(--color-muted);
  font-weight: 600;
  margin-bottom: 10px;
  display: block;
}

.qa-preset-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.qa-preset-card {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 14px;
  background: var(--surface-subtle);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  color: var(--color-text);
  font-size: 12.5px;
  text-align: left;
  cursor: pointer;
  transition: var(--transition-smooth);
}

.qa-preset-card:hover {
  border-color: var(--color-primary);
  background: var(--color-hover-bg);
  transform: translateY(-1px);
}

.qa-preset-bullet {
  color: var(--color-primary);
  font-size: 11px;
  flex-shrink: 0;
}

.qa-preset-text {
  flex: 1;
  line-height: 1.4;
}

/* Chat Messages */
.qa-message-row {
  display: flex;
  gap: 12px;
  margin-bottom: 18px;
  align-items: flex-start;
}

.qa-message-row.user {
  flex-direction: row-reverse;
}

.qa-avatar {
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.qa-avatar svg {
  width: 18px;
  height: 18px;
}

.qa-message-row.user .qa-avatar {
  color: #fff;
  background: var(--color-primary);
}

.qa-bubble {
  max-width: min(800px, 84%);
  padding: 13px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-subtle);
  color: var(--color-text);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.qa-message-row.user .qa-bubble {
  background: var(--color-primary);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 2px 10px var(--glow-accent);
}

.qa-bubble-content {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  line-height: 1.7;
  font-size: 14px;
}

.qa-bubble.typing {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-primary);
  font-weight: 600;
  font-size: 13px;
}

.qa-references {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--border-subtle);
}

.qa-ref-title {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--color-muted);
  margin-bottom: 8px;
}

.qa-ref-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.qa-ref-chip {
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 5px 9px;
  background: var(--surface-card);
  color: var(--color-primary);
  cursor: pointer;
  display: inline-flex;
  gap: 8px;
  align-items: center;
  max-width: 100%;
  font-size: 12px;
  transition: var(--transition-smooth);
}

.qa-ref-chip:hover {
  border-color: var(--color-primary);
  background: var(--color-hover-bg);
}

.qa-ref-doc {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.qa-ref-score {
  color: var(--color-muted);
  font-size: 11px;
  font-style: normal;
  background: var(--surface-subtle);
  padding: 1px 5px;
  border-radius: 4px;
}

.qa-mode {
  margin-top: 8px;
  color: var(--color-muted);
  font-size: 11px;
}

/* Pinned Input Panel */
.qa-input-panel {
  flex-shrink: 0;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-card);
}

.qa-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  color: var(--color-muted);
  font-size: 12px;
}

.qa-meta-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.qa-input-tip {
  font-size: 11px;
  color: var(--color-muted);
  opacity: 0.8;
}

.qa-topk {
  width: 54px;
  height: 28px;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 0 6px;
  background: var(--surface-subtle);
  color: var(--color-text);
  font-size: 12px;
}

.qa-input-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 48px;
  gap: 10px;
  align-items: flex-end;
}

.qa-input-row textarea {
  min-height: 48px;
  max-height: 120px;
  resize: none;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px 14px;
  font: inherit;
  font-size: 13.5px;
  outline: none;
  line-height: 1.5;
  background: var(--surface-subtle);
  color: var(--color-text);
  transition: var(--transition-smooth);
}

.qa-input-row textarea:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--glow-accent);
}

.qa-send-btn {
  width: 48px;
  height: 48px;
  border: none;
  border-radius: 8px;
  color: #fff;
  background: var(--color-primary);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: background-color 0.18s ease, opacity 0.18s ease, transform 0.18s ease;
}

.qa-send-btn:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.qa-send-btn:not(:disabled):hover {
  background: var(--color-primary-dark);
  transform: translateY(-1px);
}

@media (max-width: 860px) {
  .qa-preset-grid {
    grid-template-columns: 1fr;
  }
  .qa-input-tip {
    display: none;
  }
}
</style>

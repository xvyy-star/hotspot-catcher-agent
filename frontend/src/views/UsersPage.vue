<template>
  <section class="users-page">
    <div class="page-header-row">
      <div><h2 class="page-title">用户管理</h2><p class="page-desc">管理普通用户账号状态并重置登录密码</p></div>
    </div>
    <div class="users-content">
      <form class="users-toolbar" @submit.prevent="search">
        <label class="form-item"><span>搜索账号或昵称</span><input v-model.trim="keyword" class="input-control" placeholder="输入关键词" /></label>
        <button class="primary-btn" type="submit" :disabled="loading"><Search /> 搜索</button>
        <button class="ghost-btn" type="button" :disabled="loading" @click="refresh"><RefreshCw :class="{ spinning: loading }" /> 刷新</button>
      </form>
      <p v-if="errorMessage" class="auth-error" role="alert">{{ errorMessage }}</p>
      <div class="table-wrap">
        <table class="data-table users-table">
          <thead><tr><th>账号</th><th>显示昵称</th><th>角色</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td><b>{{ user.username }}</b></td><td>{{ user.display_name }}</td>
              <td>{{ user.role === 'admin' || user.role === 'owner' ? '管理员' : '普通用户' }}</td>
              <td><span :class="['badge', user.is_active ? 'low' : 'high']">{{ user.is_active ? '启用' : '停用' }}</span></td>
              <td>{{ user.created_at || '-' }}</td>
              <td class="user-actions">
                <button v-if="user.role === 'user'" class="ghost-btn small-btn" type="button" :disabled="busyId !== null" @click="toggleUser(user)"><Power /> {{ user.is_active ? '停用' : '启用' }}</button>
                <button v-if="user.role === 'user'" class="ghost-btn small-btn" type="button" :disabled="busyId !== null" @click="openReset(user)"><KeyRound /> 重置密码</button>
                <span v-else class="muted-text">管理员受保护</span>
              </td>
            </tr>
            <tr v-if="loading"><td colspan="6" class="empty-cell">加载中...</td></tr>
            <tr v-else-if="!users.length"><td colspan="6" class="empty-cell">暂无用户</td></tr>
          </tbody>
        </table>
      </div>
      <div class="users-pagination"><span>共 {{ total }} 个账号</span><button class="ghost-btn small-btn" type="button" :disabled="page <= 1 || loading" @click="page--; refresh()">上一页</button><span>第 {{ page }} 页</span><button class="ghost-btn small-btn" type="button" :disabled="page * pageSize >= total || loading" @click="page++; refresh()">下一页</button></div>
    </div>

    <ElDialog :model-value="Boolean(resetUser)" title="重置密码" width="min(420px, calc(100vw - 32px))" :close-on-click-modal="false" :close-on-press-escape="busyId === null" :show-close="busyId === null" @update:model-value="closeReset">
      <form v-if="resetUser" class="reset-modal" @submit.prevent="submitReset">
        <p class="reset-account">{{ resetUser.username }}</p>
        <label class="form-item"><span>新密码</span><input v-model="resetForm.password" class="input-control" type="password" minlength="8" maxlength="72" required /></label>
        <label class="form-item"><span>确认密码</span><input v-model="resetForm.confirm" class="input-control" type="password" minlength="8" maxlength="72" required /></label>
        <p v-if="resetError" class="auth-error" role="alert">{{ resetError }}</p>
        <div class="modal-actions"><button class="ghost-btn" type="button" :disabled="busyId !== null" @click="closeReset">取消</button><button class="primary-btn" type="submit" :disabled="busyId !== null">保存</button></div>
      </form>
    </ElDialog>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { RefreshCw, Search, KeyRound, Power } from 'lucide-vue-next'
import { ElDialog } from 'element-plus'
import { listUsers, resetUserPassword, updateUser } from '@/api/hotspot'
import type { ManagedUser } from '@/types/hotspot'

const emit = defineEmits<{ (e: 'message', value: string): void; (e: 'error', value: unknown): void; (e: 'set-loading', value: boolean): void }>()
const users = ref<ManagedUser[]>([])
const keyword = ref(''); const page = ref(1); const pageSize = 20; const total = ref(0); const loading = ref(false); const busyId = ref<number | null>(null); const errorMessage = ref('')
const resetUser = ref<ManagedUser | null>(null); const resetError = ref(''); const resetForm = reactive({ password: '', confirm: '' })

async function refresh() {
  loading.value = true; emit('set-loading', true); errorMessage.value = ''
  try { const result = await listUsers({ keyword: keyword.value || undefined, page: page.value, page_size: pageSize }); users.value = result.items || []; total.value = result.total || 0 }
  catch (error: any) { errorMessage.value = error.response?.data?.detail || error.message || '用户列表加载失败'; emit('error', error) }
  finally { loading.value = false; emit('set-loading', false) }
}
function search() { page.value = 1; refresh() }
async function toggleUser(user: ManagedUser) {
  busyId.value = user.id
  try { const updated = await updateUser(user.id, { is_active: !user.is_active }); Object.assign(user, updated); emit('message', `${user.username} 已${user.is_active ? '启用' : '停用'}`) }
  catch (error) { emit('error', error) } finally { busyId.value = null }
}
function openReset(user: ManagedUser) { resetUser.value = user; resetForm.password = ''; resetForm.confirm = ''; resetError.value = '' }
function closeReset() {
  if (busyId.value !== null) return
  resetUser.value = null
  resetForm.password = ''
  resetForm.confirm = ''
}
async function submitReset() {
  if (resetForm.password !== resetForm.confirm) { resetError.value = '两次输入的密码不一致。'; return }
  if (new TextEncoder().encode(resetForm.password).length > 72) { resetError.value = '密码 UTF-8 编码长度至多 72 字节。'; return }
  if (!resetUser.value) return
  busyId.value = resetUser.value.id
  try { await resetUserPassword(resetUser.value.id, { new_password: resetForm.password, confirm_password: resetForm.confirm }); emit('message', '密码已重置，原有会话已失效。'); resetUser.value = null }
  catch (error: any) { resetError.value = error.response?.data?.detail || error.message || '密码重置失败' } finally { busyId.value = null }
}
onMounted(refresh)
defineExpose({ refresh })
</script>

<style scoped>
.users-toolbar { display:flex; gap:12px; align-items:end; margin-bottom:18px; }
.users-content { padding-top: 20px; }
.users-toolbar .form-item { flex:1; max-width:420px; }
.users-table th, .users-table td { white-space:nowrap; }
.user-actions { display:flex; gap:6px; align-items:center; }
.users-pagination { display:flex; flex-wrap:wrap; align-items:center; justify-content:flex-end; gap:10px; margin-top:16px; color:var(--color-muted); font-size:13px; }
.reset-account { overflow-wrap:anywhere; margin:0; }
.reset-modal { width:min(100%, 420px); display:grid; gap:16px; }
@media (max-width:600px) { .users-toolbar { align-items:stretch; flex-direction:column; } .users-toolbar .form-item { max-width:none; } .user-actions { white-space:normal; flex-wrap:wrap; } }
</style>

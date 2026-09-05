<template>
  <div class="chrome-select-container" ref="containerRef">
    <div class="chrome-select-trigger" :class="{ active: isOpen }" @click="toggleDropdown">
      <span>{{ selectedLabel }}</span>
      <ChevronDown class="chrome-select-arrow" :class="{ rotated: isOpen }" />
    </div>

    <Transition name="dropdown-fade">
      <div v-if="isOpen" class="chrome-select-dropdown">
        <div
          v-for="opt in options"
          :key="opt.value"
          class="chrome-select-option"
          :class="{ selected: modelValue === opt.value }"
          @click="selectOption(opt.value)"
        >
          {{ opt.label }}
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ChevronDown } from 'lucide-vue-next'

const props = defineProps<{
  modelValue: string | number
  options: Array<{ value: string | number; label: string }>
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | number): void
}>()

const isOpen = ref(false)
const containerRef = ref<HTMLElement | null>(null)

const selectedLabel = computed(() => {
  const selected = props.options.find(opt => opt.value === props.modelValue)
  return selected ? selected.label : ''
})

function toggleDropdown() {
  isOpen.value = !isOpen.value
}

function selectOption(val: string | number) {
  emit('update:modelValue', val)
  isOpen.value = false
}

function handleClickOutside(event: MouseEvent) {
  if (containerRef.value && !containerRef.value.contains(event.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

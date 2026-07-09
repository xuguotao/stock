import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type DataStatusResponse } from '../../api/client'

export function useTailLiveDataHealth() {
  const dataHealth = ref<DataStatusResponse | null>(null)
  const dataHealthLoadedAt = ref('')
  const loadingDataHealth = ref(false)

  async function loadDataHealth() {
    loadingDataHealth.value = true
    try {
      dataHealth.value = await api.getDataStatus()
      dataHealthLoadedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '加载数据健康度失败')
    } finally {
      loadingDataHealth.value = false
    }
  }

  return {
    dataHealth,
    dataHealthLoadedAt,
    loadingDataHealth,
    loadDataHealth,
  }
}

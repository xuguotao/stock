const STATUS_TEXT: Record<string, string> = {
  healthy: '健康',
  degraded: '待关注',
  failed: '异常',
  unavailable: '不可用',
  pending: '等待执行',
  queued: '等待 runner 接管',
  running: '执行中',
  success: '已完成',
  stale: '已失联',
  completed: '已完成',
  loading: '加载中',
}

const AUDIT_REASON_TEXT: Record<string, string> = {
  coverage_below_target: '完整度低于 99.50% 健康目标',
  symbol_fetch_failed: '部分标的获取失败',
  invalid_rows_dropped: '存在被丢弃的无效数据',
  catalog_source_empty: '目录数据源为空',
  catalog_count_changed: '目录标的数量变化超过阈值',
}

export function mootdxStatusText(status?: string) {
  return STATUS_TEXT[status ?? ''] ?? status ?? '未知'
}

export function mootdxAuditReasonText(reasons: string[] = [], fallback?: string) {
  return reasons.map((reason) => AUDIT_REASON_TEXT[reason] ?? reason).join('、') || fallback || '-'
}

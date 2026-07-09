export function statusText(status: string) {
  if (status === 'ready') return '就绪'
  if (status === 'repairable') return '可回补'
  if (status === 'unrepairable') return '不可回补'
  if (status === 'partial') return '部分覆盖'
  if (status === 'no_data') return '无数据'
  if (status === 'snapshot_insufficient') return '快照不足'
  return status || '-'
}

export function statusType(status: string) {
  if (status === 'ready') return 'success'
  if (status === 'repairable' || status === 'partial') return 'warning'
  if (status === 'snapshot_insufficient') return 'warning'
  if (status === 'unrepairable' || status === 'no_data') return 'danger'
  return 'info'
}

export function dimensionLabel(dimension: string) {
  if (dimension === 'daily') return '日线'
  if (dimension === 'minute5') return '5m'
  if (dimension === 'snapshot') return '行情快照'
  if (dimension === 'xdxr') return '除权除息'
  return dimension
}

export function boardText(board: string) {
  if (board === 'STAR') return '科创板'
  if (board === 'CHINEXT') return '创业板'
  if (board === 'MAIN') return '主板'
  return board || '-'
}

export function formatCoverage(value: number) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`
}

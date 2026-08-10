export const HEALTH_STYLES = {
  normal: { bg: '#166534', border: '#22c55e', label: 'Normal' },
  warning: { bg: '#854d0e', border: '#eab308', label: 'Warning' },
  fault_predicted: { bg: '#9a3412', border: '#f97316', label: 'Fault predicted' },
  fault: { bg: '#7f1d1d', border: '#ef4444', label: 'Fault' },
}

export function healthStyle(status) {
  return HEALTH_STYLES[status] ?? HEALTH_STYLES.normal
}

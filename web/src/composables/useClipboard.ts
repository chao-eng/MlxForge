// 局域网 http 属于非安全上下文，navigator.clipboard 不可用，只能退回 execCommand。
// 降级需要临时 textarea，DOM 操作集中在这里，避免污染组件。
export async function copyToClipboard(text: string): Promise<void> {
  if (window.isSecureContext && navigator.clipboard !== undefined) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // 权限被拒时继续走降级方案
    }
  }

  const helper = document.createElement('textarea')
  helper.value = text
  helper.setAttribute('readonly', '')
  // 移出视口，避免复制瞬间页面滚动
  helper.style.position = 'fixed'
  helper.style.top = '0'
  helper.style.left = '-9999px'
  document.body.appendChild(helper)

  const selection = document.getSelection()
  const previousRange =
    selection !== null && selection.rangeCount > 0 ? selection.getRangeAt(0) : null
  let copied = false
  try {
    helper.select()
    helper.setSelectionRange(0, text.length)
    copied = document.execCommand('copy')
  } finally {
    document.body.removeChild(helper)
    // 恢复原有选区，不让复制动作清掉用户选中的内容
    if (previousRange !== null) {
      selection?.removeAllRanges()
      selection?.addRange(previousRange)
    }
  }

  if (!copied) {
    throw new Error('复制失败')
  }
}

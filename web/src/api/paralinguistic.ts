/**
 * 副语言标签说明。官方只给了标签清单，中文含义按标签命名约定整理，
 * 新增标签时同时更新 api.md 的清单。
 */
export interface TagRow {
  tag: string
  desc: string
}

export const TAGS: TagRow[] = [
  { tag: '[Breathing]', desc: '换气声、呼吸声' },
  { tag: '[Cough]', desc: '咳嗽声' },
  { tag: '[Sigh]', desc: '叹气声' },
  { tag: '[Laughter]', desc: '笑声' },
  { tag: '[Surprise-ah]', desc: '惊讶的「啊」' },
  { tag: '[Surprise-oh]', desc: '惊讶的「哦」' },
  { tag: '[Dissatisfaction-hnn]', desc: '不满的「哼」' },
  { tag: '[Uhm]', desc: '迟疑、思考时的口头填充音' },
  { tag: '[Confirmation-en]', desc: '表示肯定的「嗯」' },
  { tag: '[Question-ei]', desc: '疑问的「诶？」' },
  { tag: '[Question-ah]', desc: '疑问的「啊？」' },
  { tag: '[Question-en]', desc: '疑问的「嗯？」' },
  { tag: '[Question-oh]', desc: '疑问的「哦？」' },
  { tag: '[Question-huh]', desc: '疑问的「哈？」' },
]

import { useEffect, useId, useRef, useState } from 'react'

const TIME_RE = /(\d{1,2})\s*[:：]\s*(\d{2})/g
const STEP_MIN = 15

const pad = (n) => String(n).padStart(2, '0')

/** "08:00, 12:30，18:00" → ["08:00", "12:30", "18:00"]（排序去重，非法项丢弃） */
export function parseReminderTimes(raw) {
  const found = []
  const text = String(raw || '')
  TIME_RE.lastIndex = 0
  let match = TIME_RE.exec(text)
  while (match !== null) {
    const hour = Number(match[1])
    const minute = Number(match[2])
    if (hour <= 23 && minute <= 59) {
      found.push(`${pad(hour)}:${pad(minute)}`)
    }
    match = TIME_RE.exec(text)
  }
  return [...new Set(found)].sort()
}

/** 时间轴刻度：每 15 分钟一档，已选的非整点时间也补一格，避免选中的时间在轴上找不到 */
function buildSlots(selected) {
  const slots = []
  for (let minutes = 0; minutes < 24 * 60; minutes += STEP_MIN) {
    slots.push(`${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`)
  }
  selected.forEach((item) => {
    if (!slots.includes(item)) slots.push(item)
  })
  return slots.sort()
}

export default function ReminderTimes({ value, onChange }) {
  const times = parseReminderTimes(value)
  const slots = buildSlots(times)
  const [cursor, setCursor] = useState(0)
  const stripRef = useRef(null)
  const slotRefs = useRef([])
  const uid = useId()

  const scrollToIndex = (index, smooth) => {
    const el = slotRefs.current[index]
    if (el) el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', inline: 'center', block: 'nearest' })
  }

  // 打开时滚到当前时刻（已有提醒时间则滚到第一个提醒）
  useEffect(() => {
    const strip = stripRef.current
    if (!strip) return
    const now = new Date()
    const nowSlot = `${pad(now.getHours())}:${pad(Math.floor(now.getMinutes() / STEP_MIN) * STEP_MIN)}`
    const anchor = times[0] || nowSlot
    const index = slots.indexOf(anchor)
    if (index >= 0) {
      strip.scrollLeft = Math.max(0, slotRefs.current[index].offsetLeft - strip.clientWidth / 2 + 24)
      setCursor(index)
    }
    // 只在挂载时定位
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 鼠标滚轮上下滚动时，时间轴左右移动
  useEffect(() => {
    const strip = stripRef.current
    if (!strip) return
    const onWheel = (event) => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return
      event.preventDefault()
      strip.scrollLeft += event.deltaY
    }
    strip.addEventListener('wheel', onWheel, { passive: false })
    return () => strip.removeEventListener('wheel', onWheel)
  }, [])

  const toggle = (time, index) => {
    setCursor(index)
    const next = times.includes(time) ? times.filter((item) => item !== time) : [...times, time]
    onChange(parseReminderTimes(next.join(',')).join(','))
  }

  const onKeyDown = (event) => {
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault()
      const next = Math.min(slots.length - 1, Math.max(0, cursor + (event.key === 'ArrowRight' ? 1 : -1)))
      setCursor(next)
      scrollToIndex(next, true)
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      const next = event.key === 'Home' ? 0 : slots.length - 1
      setCursor(next)
      scrollToIndex(next, true)
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      toggle(slots[cursor], cursor)
    }
  }

  return (
    <div className="reminder-times">
      <div className="reminder-summary">
        {times.length > 0
          ? times.map((item) => (
            <span className="remind-chip" key={item}>
              {item}
              <button
                type="button"
                className="remind-chip-remove"
                aria-label={`删除 ${item} 这个提醒时间`}
                onClick={() => toggle(item, slots.indexOf(item))}
              >
                ×
              </button>
            </span>
          ))
          : <span className="reminder-empty">还没有提醒时间</span>}
      </div>

      <div
        className="time-strip"
        ref={stripRef}
        role="listbox"
        tabIndex={0}
        aria-label="提醒时间时间轴，左右方向键移动，回车选择"
        aria-activedescendant={`${uid}-slot-${cursor}`}
        onKeyDown={onKeyDown}
      >
        {slots.map((item, index) => {
          const selected = times.includes(item)
          return (
            <button
              key={item}
              id={`${uid}-slot-${index}`}
              ref={(el) => { slotRefs.current[index] = el }}
              type="button"
              role="option"
              aria-selected={selected}
              tabIndex={-1}
              data-time={item}
              className={`time-slot${selected ? ' selected' : ''}${index === cursor ? ' cursor' : ''}`}
              onClick={() => toggle(item, index)}
            >
              {item}
            </button>
          )
        })}
      </div>

      <p className="reminder-hint">
        左右滚动选择时刻，点一下加入提醒，再点一次取消；留空表示按需服用。
      </p>
    </div>
  )
}

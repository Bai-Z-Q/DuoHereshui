import { useState, useEffect, useCallback } from 'react'
import { useApp } from '../App.jsx'
import * as api from '../api'

export default function ProfilePage() {
  const { toast, username, setUsername } = useApp()
  const [f, setF] = useState({
    username: '', age: '', gender: '', height: '', weight: '',
    chronicConditions: '', allergies: '', specialGroup: '',
  })

  const set = (k) => (e) => setF(prev => ({ ...prev, [k]: e.target.value }))

  const load = useCallback(async () => {
    try {
      const u = await api.getUserProfile()
      setF({
        username: u.username || '',
        age: u.age || '',
        gender: u.gender || '',
        height: u.height || '',
        weight: u.weight || '',
        chronicConditions: (u.chronic_conditions || []).join(', '),
        allergies: (u.allergies || []).join(', '),
        specialGroup: u.special_group || '',
      })
      if (u.username) setUsername(u.username)
    } catch (e) { /* 忽略 */ }
  }, [setUsername])

  useEffect(() => { load() }, [load])

  const save = async (e) => {
    e.preventDefault()
    const data = {
      username: f.username,
      age: parseInt(f.age) || null,
      gender: f.gender || null,
      height: parseFloat(f.height) || null,
      weight: parseFloat(f.weight) || null,
      chronic_conditions: f.chronicConditions.split(',').map(s => s.trim()).filter(Boolean),
      allergies: f.allergies.split(',').map(s => s.trim()).filter(Boolean),
      special_group: f.specialGroup || null,
    }
    try {
      await api.saveUserProfile(data)
      toast('档案保存成功')
      setUsername(data.username || '用户')
      localStorage.setItem('medical_username', data.username || username)
    } catch (err) { toast(err.message, 'error') }
  }

  return (
    <section className="view active" id="view-profile">
      <h2 className="page-title">健康档案</h2>
      <p style={{ color: 'var(--muted)', marginBottom: 16 }}>
        这些信息仅用于个性化建议，帮助多喝热水更准确地评估用药风险。
      </p>
      <form onSubmit={save}>
        <div className="form-row">
          <div className="form-group"><label>昵称</label>
            <input type="text" value={f.username} onChange={set('username')} placeholder="如何称呼你" /></div>
          <div className="form-group"><label>年龄</label>
            <input type="number" value={f.age} onChange={set('age')} placeholder="岁" /></div>
        </div>
        <div className="form-row">
          <div className="form-group"><label>性别</label>
            <select value={f.gender} onChange={set('gender')}>
              <option value="">未选择</option>
              <option value="男">男</option>
              <option value="女">女</option>
              <option value="其他">其他</option>
            </select></div>
          <div className="form-group"><label>身高</label>
            <input type="number" value={f.height} onChange={set('height')} placeholder="cm" /></div>
          <div className="form-group"><label>体重</label>
            <input type="number" value={f.weight} onChange={set('weight')} placeholder="kg" /></div>
        </div>
        <div className="form-group"><label>慢性病（逗号分隔）</label>
          <input type="text" value={f.chronicConditions} onChange={set('chronicConditions')} placeholder="如：高血压, 糖尿病" /></div>
        <div className="form-group"><label>过敏史（逗号分隔）</label>
          <input type="text" value={f.allergies} onChange={set('allergies')} placeholder="如：青霉素, 头孢" /></div>
        <div className="form-group"><label>特殊人群</label>
          <select value={f.specialGroup} onChange={set('specialGroup')}>
            <option value="">无</option>
            <option value="pregnant">孕期</option>
            <option value="nursing">哺乳期</option>
            <option value="child">儿童</option>
            <option value="elderly">老年人</option>
          </select></div>
        <button type="submit" className="btn-primary">保存档案</button>
      </form>
    </section>
  )
}

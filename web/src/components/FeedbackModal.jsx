import { useState } from 'react'
import * as api from '../api'

export default function FeedbackModal({ medication, onClose, onSuccess }) {
  const [symptomImprovement, setSymptomImprovement] = useState('')
  const [sideEffects, setSideEffects] = useState('')
  const [rating, setRating] = useState(3)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!medication) return
    setSubmitting(true)
    try {
      await api.createMedicationFeedback({
        medication_id: medication.medication_id,
        symptom_improvement: symptomImprovement.trim() || null,
        side_effects: sideEffects.trim() || null,
        effectiveness_rating: rating,
        notes: notes.trim() || null,
      })
      onSuccess?.('反馈已保存')
      onClose()
    } catch (e) {
      alert(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (!medication) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>用药反馈：{medication.drug_name}</h3>
          <button className="btn-link" onClick={onClose}>关闭</button>
        </div>

        <div className="form-group">
          <label>症状改善情况</label>
          <textarea
            value={symptomImprovement}
            onChange={(e) => setSymptomImprovement(e.target.value)}
            placeholder="例如：头痛明显减轻，服药后30分钟起效"
            rows="3"
          />
        </div>

        <div className="form-group">
          <label>副作用记录</label>
          <textarea
            value={sideEffects}
            onChange={(e) => setSideEffects(e.target.value)}
            placeholder="例如：轻微胃部不适，饭后服用可缓解"
            rows="3"
          />
        </div>

        <div className="form-group">
          <label>有效性评分</label>
          <div className="rating-group">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                className={`rating-btn ${rating === n ? 'active' : ''}`}
                onClick={() => setRating(n)}
              >
                {n}
              </button>
            ))}
          </div>
          <div className="rating-labels">
            <span>无效</span>
            <span>一般</span>
            <span>有效</span>
            <span>很好</span>
            <span>非常有效</span>
          </div>
        </div>

        <div className="form-group">
          <label>其他备注</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="其他需要记录的信息"
            rows="2"
          />
        </div>

        <div className="modal-actions">
          <button
            className="btn-primary-sm"
            onClick={handleSubmit}
            disabled={submitting}
          >
            {submitting ? '保存中…' : '保存反馈'}
          </button>
          <button className="btn-link" onClick={onClose}>取消</button>
        </div>
      </div>
    </div>
  )
}

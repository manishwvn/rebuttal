import { useEffect, useState } from 'react'
import type { AgWidgetField, AgWidgetParams } from 'ag-studio'

export interface WidgetRows {
  fields: AgWidgetField[]
  rows: Record<string, unknown>[]
}

export function useWidgetRows(params: AgWidgetParams, slots: string[], minFields = 0): WidgetRows | null {
  const { sort, widgetApi } = params
  const mapping: Partial<Record<string, AgWidgetField[]>> = params.dataMapping
  const [response, setResponse] = useState<WidgetRows | null>(null)
  const fieldCount = slots.reduce((n, slot) => n + (mapping[slot]?.length ?? 0), 0)
  // An edit-mode remap can leave a fieldset with fewer fields than the widget indexes.
  const complete = slots.every((slot) => (mapping[slot]?.length ?? 0) > 0) && fieldCount >= minFields

  useEffect(() => {
    if (!complete) {
      widgetApi.setDisplayState('incompleteDataMapping')
      return
    }
    const fields = slots.flatMap((slot) => mapping[slot] ?? [])
    let current = true
    // Studio's default loading state is a full overlay that hides the toolbar; prominent: false avoids both.
    widgetApi.setDisplayState('loading', { prominent: false })
    widgetApi
      .getData({ fields })
      .then(({ results }) => {
        if (!current) return
        widgetApi.setDisplayState(results.rows.length === 0 ? 'noData' : 'displayed')
        // Studio keys each returned row value by its field's key, so read row[field.key].
        setResponse({ fields, rows: results.rows })
      })
      .catch(() => {
        if (current) widgetApi.setDisplayState('noData')
      })
    return () => {
      current = false
    }
  }, [complete, mapping, slots, sort, widgetApi])

  return complete ? response : null
}

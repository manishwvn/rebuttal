import { useEffect, useState } from 'react'
import type { AgWidgetField, AgWidgetParams } from 'ag-studio'

export interface WidgetRows {
  fields: AgWidgetField[]
  rows: Record<string, unknown>[]
}

export function useWidgetRows(params: AgWidgetParams, slots: string[]): WidgetRows | null {
  const { sort, widgetApi } = params
  const mapping: Partial<Record<string, AgWidgetField[]>> = params.dataMapping
  const [response, setResponse] = useState<WidgetRows | null>(null)
  const complete = slots.every((slot) => (mapping[slot]?.length ?? 0) > 0)

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

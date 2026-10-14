import type { AgDefaultWidgetDefinition } from 'ag-studio'
import type { AgRegistry, AgWidgetDefinition } from 'ag-studio-react'
import { createWidgets } from 'ag-studio-react'
import AgreementWidget from './AgreementWidget'
import DeadlineListWidget from './DeadlineListWidget'
import MoneySplitWidget from './MoneySplitWidget'
import RankedBarsWidget from './RankedBarsWidget'

export const WIDGET_TYPE = {
  rankedBars: 'rb-ranked-bars',
  moneySplit: 'rb-money-split',
  deadlines: 'rb-deadlines',
  agreement: 'rb-agreement',
} as const

// Studio's default widgets plus the four Rebuttal widgets, so the custom widget ids are typed.
export interface RebuttalRegistry extends AgRegistry {
  widgets: readonly (
    | AgDefaultWidgetDefinition
    | AgWidgetDefinition<typeof WIDGET_TYPE.rankedBars>
    | AgWidgetDefinition<typeof WIDGET_TYPE.moneySplit>
    | AgWidgetDefinition<typeof WIDGET_TYPE.deadlines>
    | AgWidgetDefinition<typeof WIDGET_TYPE.agreement>
  )[]
}

const rankedBars: AgWidgetDefinition<typeof WIDGET_TYPE.rankedBars> = {
  id: WIDGET_TYPE.rankedBars,
  label: 'Ranked bars',
  comp: RankedBarsWidget,
  defaultSize: { width: 400, height: 300 },
  minSize: { width: 200, height: 150 },
  dataMapping: {
    category: { type: 'field', supportedRoles: ['category'], required: true },
    value: { type: 'field', supportedRoles: ['numeric'], required: true },
  },
  form: (params) =>
    params.createDefaults({
      dataMappingItems: [
        { key: 'category', label: 'Category' },
        { key: 'value', label: 'Value' },
      ],
    }),
}

const moneySplit: AgWidgetDefinition<typeof WIDGET_TYPE.moneySplit> = {
  id: WIDGET_TYPE.moneySplit,
  label: 'Money split',
  comp: MoneySplitWidget,
  defaultSize: { width: 300, height: 300 },
  minSize: { width: 150, height: 150 },
  dataMapping: {
    parts: { type: 'fieldset', supportedRoles: ['numeric'], required: true },
  },
  form: (params) =>
    params.createDefaults({
      dataMappingItems: [{ key: 'parts', label: 'Parts' }],
    }),
}

const deadlines: AgWidgetDefinition<typeof WIDGET_TYPE.deadlines> = {
  id: WIDGET_TYPE.deadlines,
  label: 'Deadline list',
  comp: DeadlineListWidget,
  defaultSize: { width: 600, height: 400 },
  minSize: { width: 300, height: 200 },
  dataMapping: {
    cols: { type: 'fieldset', supportedRoles: ['category', 'temporal', 'numeric'], required: true, sort: true },
  },
  form: (params) =>
    params.createDefaults({
      dataMappingItems: [{ key: 'cols', label: 'Columns' }],
    }),
}

const agreement: AgWidgetDefinition<typeof WIDGET_TYPE.agreement> = {
  id: WIDGET_TYPE.agreement,
  label: 'Model vs final agreement',
  comp: AgreementWidget,
  defaultSize: { width: 300, height: 150 },
  minSize: { width: 150, height: 100 },
  dataMapping: {
    metrics: { type: 'fieldset', supportedRoles: ['numeric'], required: true },
  },
  form: (params) =>
    params.createDefaults({
      dataMappingItems: [{ key: 'metrics', label: 'Metrics' }],
    }),
}

// Module-level so the reference is stable: Studio resets its state whenever the widgets prop changes reference.
export const RB_WIDGETS = createWidgets<RebuttalRegistry>({
  additionalTypes: [rankedBars, moneySplit, deadlines, agreement],
  menu: [
    {
      label: 'Rebuttal',
      widgetIds: [WIDGET_TYPE.rankedBars, WIDGET_TYPE.moneySplit, WIDGET_TYPE.deadlines, WIDGET_TYPE.agreement],
    },
  ],
})

# AG Studio: research note

Research note for the AG Grid sponsor prize (the Analytics tab). Written 2026-10-09. Facts are checked against the sources below; anything not checked is listed under "NOT VERIFIED" in section 9.

**Sources checked on 2026-10-09**

- npm registry (read-only `npm view`): `ag-studio-react@3.0.0`, `ag-studio@3.0.0`, `ag-grid-community@36.2.0`, `ag-charts-community@14.2.0`.
- AG Studio 3.0.0 React docs, fetched as Markdown by appending `.md` to the page URL: installation, compatibility, react-best-practices, loading-data, state, theming, custom-widgets, widget-catalogue, enterprise-licence, licence-install, quick-start, overview, ai, ai-quickstart, ai-tools.
- Project skill `.claude/skills/ag-dev/references/studio/` (the `ag-mcp` server has no Studio pages).

Docs root used below: `https://www.ag-grid.com/studio/archive/3.0.0/react/`

## 1. What it is

AG Studio is an embedded analytics component for JavaScript and React apps. It is built on AG Grid and AG Charts, and provides:

- a drag-and-drop report builder (`mode: "edit"`) and a locked report view (`mode: "view"`);
- a built-in in-browser data engine: joins through relationships, aggregation, filters and calculated fields;
- cross-filtering between widgets, and page-level filters;
- a Studio Theming API;
- a whole report saved as one JSON state object.

The host app owns routing, auth, data fetching and persistence. AI features send data only to the endpoint the host provides (section 7).

Links: [product](https://www.ag-grid.com/studio/) | [overview](https://www.ag-grid.com/studio/archive/3.0.0/react/overview/) | [quick start](https://www.ag-grid.com/studio/archive/3.0.0/react/quick-start/) | [tutorial](https://www.ag-grid.com/studio/archive/3.0.0/react/tutorial/)

## 2. Packages and versions (verified on npm)

| Package | Version | npm licence field | Dependencies (ranges from npm) |
| --- | --- | --- | --- |
| `ag-studio-react` | 3.0.0 (published 2026-09-16) | Commercial | `ag-studio` 3.0.0, `ag-grid-enterprise` ~36.2.0, `ag-grid-react` ~36.2.0, `ag-stack` ~36.2.0 |
| `ag-studio` | 3.0.0 | Commercial | `ag-grid-enterprise` ~36.2.0, `ag-charts-enterprise` ~14.2.0, `ag-stack` ~36.2.0, `tslib` ^2.3.0 |

Compatibility ([docs table](https://www.ag-grid.com/studio/archive/3.0.0/react/compatibility/)):

- Studio 3.0 = AG Grid 36.2 = AG Charts 14.2. Studio 2.1 = 36.1 / 14.1. Studio 2.0 = 36.0 / 14.0.
- React 17 to 19+ is supported for Studio 2 to 3+. TypeScript >= 5.8.3 for Studio 2 to 3+.
- `ag-studio-react` and `ag-studio` must be the same version.
- Standalone AG Grid or AG Charts in the same app should be upgraded to the matching line. AG Grid with legacy CSS themes must be migrated to the Theming API or kept on another page.

Our frontend (`frontend/package.json` and lockfile): `ag-grid-community` 36.2.0 is pinned in the lockfile, and `ag-grid-react` is `^36.2.0`. That matches the Studio 3.0 line.

Warning: the project skill's rule of thumb ("Studio version = grid version - 34", in `ag-dev/references/studio/recommendations.md`) gives 2.0 for grid 36.0, but it does not hold for 3.0.0 (grid 36.2). Use the compatibility table, not the rule. The skill should be corrected separately.

Install: `npm install ag-studio-react` (this pulls in `ag-studio`). In a Studio app, do not register AG Grid or AG Charts modules or call their `LicenseManager`; Studio registers what it needs (project skill, common mistakes). The Inbox keeps its own `AgGridProvider` with `ag-grid-community` modules. That is a separate AG Grid instance and stays separate.

## 3. Licence and cost

- Studio is a commercial product. The [enterprise licence](https://www.ag-grid.com/studio/archive/3.0.0/react/enterprise-licence/) page says every deployment requires a licence.
- Without a key, Studio works locally but shows a watermark and console warnings. The [installation](https://www.ag-grid.com/studio/archive/3.0.0/react/installation/) and [licence install](https://www.ag-grid.com/studio/archive/3.0.0/react/licence-install/) pages say a trial licence removes both, and that a trial is needed to "test in production". The trial's length is NOT VERIFIED (section 9).
- Our plan: no licence and no spend. The watermark is accepted under the AG Grid staff comment on Discord, as recorded in the repo `CLAUDE.md`. That comment was given for AG Grid, not Studio specifically, and is not independently verified. We never buy a licence.
- If Manish chooses to request a trial key, it goes in as `<AgStudioProvider licenseKey={...}>` ([licence install](https://www.ag-grid.com/studio/archive/3.0.0/react/licence-install/)). It must come from an env var and never from git. Ask Manish first. The docs' example puts the key in client code, so it ends up in the browser bundle.
- Scope: an AG Studio licence covers Studio and its built-in grid and chart widgets only. The enterprise licence page says it "does not extend to AG Grid Enterprise or AG Charts Enterprise used outside of AG Studio, including in custom widgets", which need their own licences. Custom widgets (section 6) must not use AG Grid or AG Charts Enterprise features.

## 4. How it embeds in React

```tsx
import { AgStudio } from 'ag-studio-react'

// data and theme keep the same reference between renders (useState / useMemo)
<div style={{ height: 720 }}>   {/* Studio fills its parent, so the parent needs a height */}
  <AgStudio data={data} mode="view" theme={theme} initialState={state} />
</div>
```

- `mode` is `"view"` (default) or `"edit"`. The Analytics tab uses `"view"`.
- `data` is `{ sources: [{ id, data: [plain objects] }] }` ([loading data](https://www.ag-grid.com/studio/archive/3.0.0/react/loading-data/)). Keep it stable with `useState` or `useMemo`. Inline objects reset Studio state on every render ([React best practices](https://www.ag-grid.com/studio/archive/3.0.0/react/react-best-practices/)). Callbacks should use `useCallback`; event handlers do not need it.
- Refresh: updating `data` after init reloads the rows of existing sources only. Adding or removing sources, or changing fields, is ignored. For a structural change, remount with a React `key`.
- `initialState` is read once, at init. Changing it later does nothing. Read and write the report through the ref with `api.getState()` and `api.setState(state)` ([state](https://www.ag-grid.com/studio/archive/3.0.0/react/state/)).
- Report state shape: `{ pages: [{ id, widgets: { <id>: { type, dataMapping, format } }, widgetLayout: { <id>: { xTrack, yTrack, xSpan, ySpan } } }], selectedPageId, panels }`.
- Widget type ids are strings such as `value`, `grid`, `bar-chart-grouped`, `bar-chart-stacked`, `column-chart-grouped`, `pie-chart`, `donut-chart`, `list-filter`, `text`. The full list is in the [widget catalogue](https://www.ag-grid.com/studio/archive/3.0.0/react/widget-catalogue/).
- Dev validations: call `enableStudioDevValidations()` from `ag-studio` once, only in development builds (`import.meta.env.DEV` in Vite). See [installation](https://www.ag-grid.com/studio/archive/3.0.0/react/installation/).

## 5. Theming

- Studio has its own Theming API, and its default theme is exported as `studioTheme` from `ag-studio`. Build a theme with `studioTheme.withParams({...})` and pass it as the `theme` prop ([theming](https://www.ag-grid.com/studio/archive/3.0.0/react/theming/)).
- Colour mode comes from the `data-ag-theme-mode` attribute on `<html>` or `<body>`, or on any ancestor with the `ag-theme-mode` class. The built-in modes are `light`, `dark` and `dark-blue`. Define your own mode by passing its name as the second argument, for example `studioTheme.withParams({...}, 'light')`.
- Widget params go through the same theme: `gridCellTextColor` for grid widgets and `chartAxisLineColor` for chart widgets. The [theme builder](https://www.ag-grid.com/studio/archive/3.0.0/react/theme-builder/) can export theme code.
- Do not theme Studio with AG Grid's standalone `themeQuartz` or with CSS theme files (project skill).
- Palette: `preview/template.html` uses accent `#0e6b63` in light mode and `#4cc2b4` in dark mode. The Inbox already uses `themeQuartz` with that palette and the same `data-ag-theme-mode` attribute (`frontend/src/components/Inbox.tsx`), so one attribute switches both. The Studio theme params are the part still to build.

## 6. Custom widgets (planned for part 2, not built in part 1)

- Define a widget with `AgWidgetDefinition`: `id`, `label`, `icon`, `dataMapping`, `form`, `defaultState`, `formatShape`, `extends` (pre-configures a built-in type such as `grid`) and `comp` (the React component). See [custom widgets](https://www.ag-grid.com/studio/archive/3.0.0/react/custom-widgets/).
- Register the definitions with the `widgets` prop, built with `createWidgets` imported from `ag-studio-react`. Do not import it from `ag-studio`, so the React defaults apply.
- `comp` receives `AgWidgetParams`: `api`, `context`, `widgetId`, `widgetType`, `format`, `dataMapping`, `sort`, `config` and `widgetApi`. Load data with `widgetApi.getData(request)`. Set the display state with `widgetApi.setDisplayState(...)`: `displayed`, `loading`, `noData` or `incompleteDataMapping`.
- The licence limit in section 3 applies: no AG Grid or AG Charts Enterprise features inside custom widgets.

## 7. Studio Agent Framework (planned for part 3)

- Users explore data and build or change dashboards in natural language, using an LLM that the host app supplies. Studio ships no model, server or backend, and sends no data to an AG Grid service ([agent overview](https://www.ag-grid.com/studio/archive/3.0.0/react/ai/)). It is opt-in. The project skill says it is experimental and its behaviour varies by LLM.
- Enable it by registering the module, `<AgStudioProvider modules={[AgStudioAiModule]}>`, then pass `ai={({ api }) => createAiHarness(api, { adapter, promptStarters, models })}` to `AgStudio` ([AI quick start](https://www.ag-grid.com/studio/archive/3.0.0/react/ai-quickstart/)).
- `createAiHarness` gives five built-in agents, with the lead agent fronting the chat. Tools can be customised ([built-in agents](https://www.ag-grid.com/studio/archive/3.0.0/react/ai-builtin-agents/), [tools](https://www.ag-grid.com/studio/archive/3.0.0/react/ai-tools/)).
- The adapter, which translates Studio's request format to a provider's format, is NOT shipped. The docs' example is an OpenAI Responses adapter that calls the provider from the browser, and the docs warn that this may expose the key. They say to route the requests through your own endpoint.
- For us: the adapter calls our own backend, a future read-only proxy to Groq. No key goes in the frontend. We write that adapter ourselves.

## 8. Decision for this repo

- Use AG Studio for the Analytics tab: `mode="view"` with a pre-built report, lazy-loaded (`React.lazy`) so the main bundle does not grow.
- Cost: npm install only. No licence purchase. The watermark is accepted under the Discord comment (section 3).
- Fallback if Studio fails to build or run: AG Grid Community plus AG Charts Community with the same endpoints. Both are MIT on npm (`ag-grid-community` 36.2.0, `ag-charts-community` 14.2.0).

Fallback used: no

## 9. NOT VERIFIED

- Watermark behaviour in a production build, and its exact appearance.
- Whether the Discord confirmation covers Studio specifically. It was given for AG Grid (repo `CLAUDE.md`).
- The 45-day trial length. The trial and pricing pages we could reach do not state it, and the pricing page is sales copy.
- Bundle-size impact of Studio and of lazy loading. To be measured in the frontend PR.
- Studio with Vite 8 and React 19.2. To be confirmed when the frontend PR builds.
- The Agent Framework with Groq. It needs the backend proxy and an adapter that we write.
- Custom widget runtime behaviour beyond the documented API.

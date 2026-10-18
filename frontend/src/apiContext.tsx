import { createContext, useContext } from 'react'
import { api, type Api } from './api'

// Components read the API through this context. Outside a provider they get the real backend client.
export const ApiContext = createContext<Api>(api)

// True inside the judge demo, whose writes go to an in-memory mock, so the UI must not claim they reached PayPal.
export const DemoContext = createContext(false)

export function useApi(): Api {
  return useContext(ApiContext)
}

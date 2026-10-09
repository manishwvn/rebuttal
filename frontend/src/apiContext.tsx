import { createContext, useContext } from 'react'
import { api, type Api } from './api'

// Components read the API through this context. Outside a provider they get the real backend client.
export const ApiContext = createContext<Api>(api)

export function useApi(): Api {
  return useContext(ApiContext)
}

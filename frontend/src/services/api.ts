/**
 * API service — Axios instance configured for the FastAPI proxy.
 * No JWT interceptor needed: the httpOnly cookie is sent automatically
 * with every same-origin request.
 */

import axios from 'axios'

const API_BASE_URL = '/api'

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Ensure cookies are sent with requests
})

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Session expired — redirect to login
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

/**
 * Helper for multipart upload (no Content-Type — let browser set boundary).
 * Cookies are sent automatically.
 */
export function createMultipartApi() {
  const instance = axios.create({
    baseURL: API_BASE_URL,
    withCredentials: true,
  })

  instance.interceptors.response.use(
    (response) => response,
    (error) => {
      if (error.response?.status === 401) {
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }
  )

  return instance
}

export default api

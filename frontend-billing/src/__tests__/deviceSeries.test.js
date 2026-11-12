// @vitest-environment jsdom
import { beforeEach, expect, it } from 'vitest'
import { readDeviceSeries, rememberDeviceSeries } from '../utils/deviceSeries'

beforeEach(() => localStorage.clear())

it('keeps offline numbering scoped to the business and local/LAN server', () => {
  rememberDeviceSeries('BUSINESS-A', 'http://lan-master:8000', '00A')
  expect(readDeviceSeries('BUSINESS-A', 'http://lan-master:8000')).toBe('00A')
  expect(readDeviceSeries('BUSINESS-B', 'http://lan-master:8000')).toBeNull()
  expect(readDeviceSeries('BUSINESS-A', 'http://localhost:8000')).toBeNull()
})

it('refuses invalid namespaces and does not replace a valid one with absent settings', () => {
  rememberDeviceSeries('BUSINESS-A', 'local', '00A')
  rememberDeviceSeries('BUSINESS-A', 'local', undefined)
  expect(readDeviceSeries('BUSINESS-A', 'local')).toBe('00A')
  rememberDeviceSeries('BUSINESS-B', 'local', '../')
  expect(readDeviceSeries('BUSINESS-B', 'local')).toBeNull()
})

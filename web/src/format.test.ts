import { expect, test } from 'vitest'
import { bytes, storageLevel } from './format'

test('bytes', () => {
  expect(bytes(512)).toBe('512 bytes')
  expect(bytes(1536)).toBe('1.5 KB')
  expect(bytes(1.2 * 1024 ** 3)).toBe('1.2 GB')
  expect(bytes(2048 * 1024 ** 2)).toBe('2 GB')
  expect(bytes(300 * 1024 ** 2)).toBe('300 MB')
})

test('storageLevel', () => {
  expect(storageLevel(100, 1000)).toBe('ok')
  expect(storageLevel(900, 1000)).toBe('warning')
  expect(storageLevel(1000, 1000)).toBe('warning')
  expect(storageLevel(1001, 1000)).toBe('error')
})

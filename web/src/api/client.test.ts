import { expect, test, vi } from 'vitest'
import { ApiError, setUnauthorizedHandler, unwrap } from './client'

const response = (status: number, body: unknown) => new Response(JSON.stringify(body), { status })
const failure = (r: Response): Promise<ApiError> => unwrap(r).then(() => { throw new Error('expected a failure') }, (e: ApiError) => e)

test('a success envelope gives its data', async () => {
  expect(await unwrap(response(200, { success: true, data: { id: 'a' }, meta: {} }))).toEqual({ id: 'a' })
})

test('an error envelope throws its code and message', async () => {
  const error = await failure(response(404, { success: false, error: { code: 'agent_not_found', message: 'There is no agent with this id.' } }))
  expect(error).toBeInstanceOf(ApiError)
  expect([error.status, error.code, error.message]).toEqual([404, 'agent_not_found', 'There is no agent with this id.'])
})

test('a 401 signs the user out', async () => {
  const handler = vi.fn()
  setUnauthorizedHandler(handler)
  await unwrap(response(401, { success: false, error: { code: 'not_signed_in', message: 'Sign in.' } })).catch(() => {})
  expect(handler).toHaveBeenCalled()
})

test('a body that is not JSON still throws', async () => {
  const error = await failure(new Response('<html>Bad gateway</html>', { status: 502 }))
  expect([error.code, error.status]).toEqual(['http_error', 502])
})

/** localStorage that never throws: a browser that refuses storage just forgets on reload. */
export function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Refused: the setting lasts until reload.
  }
}

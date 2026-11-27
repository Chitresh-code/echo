/** One row a command offers after its name: a model, an effort level, or a state such as loading. */
export type CommandOption = {
  id: string
  label: string
  detail?: string
  /** Consecutive rows with the same group are listed under it. */
  group?: string
  /** Shown but not pickable, such as "Loading the models". */
  disabled?: boolean
  /** The value in use now. */
  selected?: boolean
}

/** A setting changed by typing `/name` at the start of a line in the message box. */
export type Command = {
  name: string
  description: string
  /** The rows for the text typed after the name, already filtered by it. */
  options: (query: string) => CommandOption[]
  /** Applies a picked row. Returns what to tell a screen reader, or null to keep the menu open (a Retry row, say). */
  apply: (option: CommandOption) => string | null
  /** Picking a row says what happened but leaves the menu open, for picking several in a row. */
  keepOpen?: boolean
}

export const matches = (text: string, query: string) => text.toLowerCase().includes(query.trim().toLowerCase())

export type Parsed =
  | { kind: 'names'; names: Command[] }
  | { kind: 'options'; command: Command; query: string }
  | { kind: 'none' }

/**
 * Reads the text after `/`: before a space it narrows the command names; after `name ` it is that
 * command's filter. An unknown name is ordinary text, so `/etc/hosts is gone` is sent as typed.
 */
export function parse(commands: Command[], query: string): Parsed {
  const space = query.search(/\s/)
  if (space < 0) {
    const names = commands.filter((c) => c.name.startsWith(query.toLowerCase()))
    return names.length ? { kind: 'names', names } : { kind: 'none' }
  }
  const command = commands.find((c) => c.name === query.slice(0, space).toLowerCase())
  return command ? { kind: 'options', command, query: query.slice(space + 1).trim() } : { kind: 'none' }
}

/** The row Up or Down moves to, wrapping at the ends. */
export const step = (length: number, at: number, by: number) => (length ? (at + by + length) % length : 0)

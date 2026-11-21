// The guide's only script. It is a file, not inline, because the page CSP allows scripts from
// this origin only. It runs in <head> so the theme is set before the page paints.

// Same storage key and values as the app, so a theme picked in either applies to both.
const THEME_KEY = 'echo.theme'
const root = document.documentElement

function storedTheme() {
  try {
    const value = localStorage.getItem(THEME_KEY)
    return value === 'dark' || value === 'light' ? value : null
  } catch {
    return null
  }
}

const systemDark = window.matchMedia('(prefers-color-scheme: dark)')
root.dataset.theme = storedTheme() ?? (systemDark.matches ? 'dark' : 'light')
// Follow the system until the reader picks a theme, like the app does.
systemDark.addEventListener('change', (e) => {
  if (!storedTheme()) root.dataset.theme = e.matches ? 'dark' : 'light'
})

document.addEventListener('DOMContentLoaded', () => {
  document.querySelector('.theme-btn')?.addEventListener('click', () => {
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark'
    root.dataset.theme = next
    try {
      localStorage.setItem(THEME_KEY, next)
    } catch {
      // Private windows can refuse storage; the choice then lasts until reload.
    }
  })

  const menu = document.querySelector('.menu-btn')
  menu?.addEventListener('click', () => {
    const open = document.body.classList.toggle('menu-open')
    menu.setAttribute('aria-expanded', String(open))
  })

  for (const pre of document.querySelectorAll('pre:not(.skillmd)')) {
    const button = document.createElement('button')
    button.className = 'copy'
    button.type = 'button'
    button.textContent = 'Copy'
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(pre.querySelector('code')?.innerText ?? pre.innerText)
        button.textContent = 'Copied'
        button.classList.add('done')
      } catch {
        button.textContent = 'Select and copy'
      }
      setTimeout(() => {
        button.textContent = 'Copy'
        button.classList.remove('done')
      }, 1600)
    })
    pre.append(button)
  }

  // "On this page", built from the article's section headings.
  const toc = document.querySelector('.toc')
  const headings = [...document.querySelectorAll('article h2[id]')]
  if (toc && headings.length > 1) {
    const title = document.createElement('p')
    title.textContent = 'On this page'
    toc.append(title)
    const links = headings.map((h) => {
      const a = document.createElement('a')
      a.href = `#${h.id}`
      a.textContent = h.textContent
      toc.append(a)
      return a
    })
    const mark = () => {
      let current = 0
      headings.forEach((h, i) => {
        if (h.getBoundingClientRect().top < 120) current = i
      })
      links.forEach((a, i) => a.classList.toggle('on', i === current))
    }
    document.addEventListener('scroll', mark, { passive: true })
    mark()
  }
})

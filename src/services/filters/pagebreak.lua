--[[
Pandoc Lua filter to turn TeX-style page break commands into DOCX page breaks.

We map commands like \newpage, \pagebreak, and \clearpage to the OOXML snippet
that Word interprets as an explicit page break. For other output formats the
default behaviour is preserved.
]]

local PAGEBREAK_OPENXML = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'

local function pagebreak_block()
  return pandoc.RawBlock('openxml', PAGEBREAK_OPENXML)
end

local function is_tex_pagebreak(text)
  return text:match('\\newpage') or text:match('\\pagebreak') or text:match('\\clearpage')
end

local function is_html_pagebreak(text)
  local t = text:lower()
  if t:match('%<%!%-%-%s*pagebreak%s*%-%-%>') then return true end
  if t:match('%<div[^>]*class%s*=%s*"[^"]*pagebreak[^"]*"[^>]*%>%s*%</div%>') then return true end
  return false
end

local function is_plaintext_pagebreak_para(el)
  -- Works even when raw_tex is disabled: detect a paragraph that only contains
  -- markers like "\\newpage" or form-feed (\f).
  local s = pandoc.utils.stringify(el):gsub('^%s+', ''):gsub('%s+$', '')
  if s == '\\newpage' or s == '\\pagebreak' or s == '\\clearpage' then
    return true
  end
  if s == '\f' then return true end
  return false
end

function RawBlock(el)
  if (el.format == 'tex' or el.format == 'latex') and is_tex_pagebreak(el.text) then
    return pagebreak_block()
  end
  if el.format == 'html' and is_html_pagebreak(el.text) then
    return pagebreak_block()
  end
end

function Para(el)
  -- If GFM filters out raw_tex, "\\newpage" becomes plain text; handle that here.
  if is_plaintext_pagebreak_para(el) then
    return pagebreak_block()
  end

  if #el.content == 1 then
    local first = el.content[1]
    if first.t == 'RawInline' and (first.format == 'tex' or first.format == 'latex') and is_tex_pagebreak(first.text) then
      return pagebreak_block()
    end
  end
end

function Div(el)
  -- Support ::: pagebreak or ::: { .pagebreak }
  if el.classes and pandoc.List.includes(el.classes, 'pagebreak') then
    return pagebreak_block()
  end
end

--[[
Convert standalone images into a figure with a caption paragraph styled for DOCX.

GFM does not enable implicit figures, so an image like ![Caption](url) becomes a
plain Image inline without caption styling. This filter keeps the image inline but
inserts a following paragraph that reuses the alt text as visible caption text,
applying the "Caption" style so users can tweak it via reference.docx.

The filter leaves images without alt text untouched and preserves the alt text
on the image for accessibility purposes.
]]

local label_counts = {}
local label_numbers = {}

local function has_caption(image)
  return image.caption and #image.caption > 0
end

local function caption_block(inlines)
  local para = pandoc.Para(inlines)
  return pandoc.Div({ para }, pandoc.Attr('', {}, { ['custom-style'] = 'Caption' }))
end

local function clone_inlines(src)
  local copy = {}
  for i = 1, #src do
    copy[i] = src[i]
  end
  return copy
end

local function trim_inlines(inlines)
  while #inlines > 0 and inlines[1].t == 'Space' do
    table.remove(inlines, 1)
  end
  while #inlines > 0 and inlines[#inlines].t == 'Space' do
    table.remove(inlines, #inlines)
  end
  return inlines
end

local function parse_attr_string(str)
  local id = str:match("^%{#([^%s}]+)%}$")
  if id then
    return id, {}
  end

  local class = str:match("^%{%.([^%s}]+)%}$")
  if class then
    return nil, { class }
  end

  local id_class = str:match("^%{#([^%s}]+)%.([^%s}]+)%}$")
  if id_class then
    local id_part, class_part = id_class:match("([^%.]+)%.(.+)")
    return id_part, { class_part }
  end

  return nil, nil
end

local function register_label(kind, identifier)
  if not identifier or identifier == '' then
    return nil
  end

  if label_numbers[identifier] then
    return label_numbers[identifier]
  end

  label_counts[kind] = (label_counts[kind] or 0) + 1
  label_numbers[identifier] = label_counts[kind]
  return label_numbers[identifier]
end

local function make_figure_block(image, identifier, extra_classes)
  local img_para = pandoc.Para({ image })
  local caption = caption_block(clone_inlines(image.caption))

  local classes = { 'figure' }
  if extra_classes then
    for _, cls in ipairs(extra_classes) do
      table.insert(classes, cls)
    end
  end

  local attr = pandoc.Attr(identifier or '', classes, {})
  register_label('fig', attr.identifier)

  return pandoc.Div({ img_para, caption }, attr)
end

local function push_para(result, inlines)
  if #inlines > 0 then
    table.insert(result, pandoc.Para(clone_inlines(inlines)))
  end
end

local function transform_para(el)
  local result = {}
  local buffer = {}
  local changed = false

  local i = 1
  while i <= #el.content do
    local inline = el.content[i]

    if inline.t == 'Image' and has_caption(inline) then
      local identifier = inline.attr and inline.attr.identifier or ''
      local classes_from_attr = nil

      if i + 1 <= #el.content and el.content[i + 1].t == 'Str' then
        local next_str = el.content[i + 1].text
        local parsed_id, parsed_classes = parse_attr_string(next_str)
        if parsed_id or parsed_classes then
          identifier = parsed_id or identifier
          classes_from_attr = parsed_classes
          i = i + 1 -- skip the attribute string
        end
      end

      push_para(result, buffer)
      buffer = {}

      table.insert(result, make_figure_block(inline, identifier, classes_from_attr))
      changed = true
    else
      table.insert(buffer, inline)
    end

    i = i + 1
  end

  push_para(result, buffer)

  if changed then
    return result
  end
end

local function parse_table_caption_para(para)
  if #para.content == 0 then
    return nil
  end

  local first = para.content[1]
  if first.t ~= 'Str' or first.text ~= ':' then
    return nil
  end

  local inlines = {}
  for i = 2, #para.content do
    inlines[#inlines + 1] = para.content[i]
  end

  if #inlines > 0 and inlines[1].t == 'Space' then
    table.remove(inlines, 1)
  end

  if #inlines == 0 then
    return nil
  end

  local identifier
  if inlines[#inlines].t == 'Str' then
    local id, _ = parse_attr_string(inlines[#inlines].text)
    if id then
      identifier = id
      table.remove(inlines, #inlines)
    end
  end

  inlines = trim_inlines(inlines)

  if #inlines == 0 then
    return nil
  end

  return {
    caption_inlines = clone_inlines(inlines),
    identifier = identifier,
  }
end

local function table_caption_block(inlines)
  local para = pandoc.Para(inlines)
  return pandoc.Div({ para }, pandoc.Attr('', {}, { ['custom-style'] = 'Caption' }))
end

local function ensure_table_identifier(raw_id)
  if raw_id and raw_id ~= '' then
    if raw_id:match('^tbl:') then
      return raw_id
    end
    return 'tbl:' .. raw_id
  end

  local next_number = (label_counts['tbl'] or 0) + 1
  return string.format('tbl:%d', next_number)
end

local function transform_blocks(blocks)
  local transformed = {}
  local i = 1

  while i <= #blocks do
    local block = blocks[i]

    if block.t == 'Para' then
      local info = parse_table_caption_para(block)
      if info and i + 1 <= #blocks and blocks[i + 1].t == 'Table' then
        local tbl = blocks[i + 1]
        local identifier = ensure_table_identifier(info.identifier or '')
        register_label('tbl', identifier)

        local caption = table_caption_block(info.caption_inlines)
        local div_attr = pandoc.Attr(identifier, { 'table' }, {})
        table.insert(transformed, pandoc.Div({ tbl, caption }, div_attr))

        i = i + 2
        goto continue
      end
    end

    table.insert(transformed, block)
    i = i + 1
    ::continue::
  end

  return transformed
end

local reference_prefix = {
  fig = "图",
  tbl = "表",
}

local function replace_reference(text)
  local replaced = false

  local new_text = text:gsub("%[@([%w:%-_.]+)%]", function(label)
    local kind = label:match("^(%a+):")
    if not kind then
      return "[@" .. label .. "]"
    end

    local number = label_numbers[label]
    if not number then
      return "[@" .. label .. "]"
    end

    local prefix = reference_prefix[kind]
    if not prefix then
      return "[@" .. label .. "]"
    end

    replaced = true
    return string.format("%s%d", prefix, number)
  end)

  if replaced then
    return pandoc.Str(new_text)
  end
end

function Pandoc(doc)
  label_counts = {}
  label_numbers = {}

  doc.blocks = transform_blocks(doc.blocks)
  -- Ensure captions are applied before we replace references.
  doc = doc:walk({ Para = transform_para })

  doc = doc:walk({
    Str = function(inline)
      return replace_reference(inline.text)
    end,
  })

  return doc
end

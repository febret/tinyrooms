function escapeHtml(s){
  return s.replace(/[&<>"'\/]/g, function (c) { return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','/':'&#x2F;'})[c]; });
}


function formatText(text) {
  // Replace [[ and ]] with <span> tags
  // Support [[<@id>text]] or [[<color>text]] formats
  
  let result = text;
  
  // Pattern to match [[@id or [[color or [[ followed by content and closing ]]
  // This regex captures: [[(@id or color)? ... ]]
  result = result.replace(/\[\[(\.\w+@?[\w|:|-]*|@[\w|:|-]*|#\w+)?\s*/g, (match, modifier) => {
    if (!modifier) {
      // Plain [[ - just opening span
      return '<span>';
    } else if (modifier.startsWith('.')) {
        cmd = modifier.substring(1); // Remove . prefix
        // Extract target if cmd is in cmd@target form
        target = null;
        const atIndex = cmd.indexOf('@');
        if (atIndex !== -1) {
            target = cmd.substring(atIndex + 1);
            cmd = cmd.substring(0, atIndex);
        }
        return `<span class="ref cmd" data-cmd="${cmd}"` + (target ? ` data-target="${target}"` : '') + '>';
    } else if (modifier.startsWith('@')) {
      // [[@id format - create span with id and class 'ref'
      const id = modifier.substring(1); // Remove @ prefix
      // Check if this ID matches the current user's username
      const isSelf = myUsername && id === myUsername;
      const classes = isSelf ? 'ref self' : 'ref';
      if (id.length === 0) {
        return `<span class="${classes}">`;
      } else {
        return `<span id="${id}" class="${classes}">`;
      }
    } else if (modifier.startsWith('#')) {
      // Hex color format - set font color
      let color = modifier.substring(1); // Remove # prefix
      // If 3-digit hex, expand it to 6-digit
      if (color.length === 3) {
        color = color[0] + color[0] + color[1] + color[1] + color[2] + color[2];
      }
      return `<span style="color: #${color}">`;
    }
  });
  
  // Replace ]] with closing span
  result = result.replace(/\]\]/g, '</span>');  
  return result;
}


function makeActionLabel(text) {
  // Find the first emoji from the right side of text and return it as label
  const emojiRegex = /(\p{Emoji_Presentation}|\p{Emoji}\uFE0F)/gu;
  let match;
  let lastEmoji = null;
  while ((match = emojiRegex.exec(text)) !== null) {
    lastEmoji = match[0];
  }
  // If you did not find any emoji, use a default label
  if (!lastEmoji) {
    lastEmoji = "...";
  }
  return lastEmoji;
}

// Text-to-speech function
function stripFormattedText(html) {
  // Create a temporary element to parse HTML
  const temp = document.createElement('div');
  temp.innerHTML = html;
  text = temp.textContent || temp.innerText || '';
  // Remove emojis and repeated punctuation characters
  text = text.replace(/[\p{Emoji_Presentation}|\p{Emoji}\uFE0F]/gu, ''); // Remove emojis
  //text = text.replace(/([!?.,])\1{2,}/g, '$1'); // Replace repeated punctuation with single
  return text;
}

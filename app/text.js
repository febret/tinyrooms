function escapeHtml(s){
  return s.replace(/[&<>"'\/]/g, function (c) { return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','/':'&#x2F;'})[c]; });
}


function formatText(text) {
  // Replace [[ and ]] with <span> tags
  // Support [[<@id>text]] or [[<color>text]] formats
  
  let result = text;
  
  // Pattern to match [[@id or [[color or [[ followed by content and closing ]]
  // This regex captures: [[(@id or color)? ... ]]
  result = result.replace(/\[\[(@\w*|#\w+)?\s*/g, (match, modifier) => {
    if (!modifier) {
      // Plain [[ - just opening span
      return '<span>';
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

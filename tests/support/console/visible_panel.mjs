// A desktop window scrolls independently of the browser document. Capture the
// pixels visible to the operator inside that window at the requested section.
export async function visiblePanelScreenshot(panel, options, anchor = panel) {
  const page = panel.page();
  await page.evaluate(() => document.fonts.ready);
  await anchor.evaluate(node => node.scrollIntoView({block: 'start', inline: 'nearest', behavior: 'instant'}));
  const clip = await panel.evaluate(node => {
    const box = node.getBoundingClientRect();
    const surface = node.closest('.window-surface');
    const bounds = surface.getBoundingClientRect();
    const x = Math.ceil(Math.max(0, box.left, bounds.left + surface.clientLeft));
    const y = Math.ceil(Math.max(0, box.top, bounds.top + surface.clientTop));
    const right = Math.floor(Math.min(innerWidth, box.right, bounds.left + surface.clientLeft + surface.clientWidth));
    const bottom = Math.floor(Math.min(innerHeight, box.bottom, bounds.top + surface.clientTop + surface.clientHeight));
    return {x, y, width: right - x, height: bottom - y};
  });
  if (clip.width <= 0 || clip.height <= 0) throw new Error('Panel is outside the active window');
  const visible = await anchor.evaluate(node => {
    const box = node.getBoundingClientRect();
    const surface = node.closest('.window-surface').getBoundingClientRect();
    const x = (Math.max(box.left, surface.left, 0) + Math.min(box.right, surface.right, innerWidth)) / 2;
    const y = (Math.max(box.top, surface.top, 0) + Math.min(box.bottom, surface.bottom, innerHeight)) / 2;
    return node.contains(document.elementFromPoint(x, y));
  });
  if (!visible) throw new Error('Panel content is obscured in the active window');
  return page.screenshot({...options, clip});
}

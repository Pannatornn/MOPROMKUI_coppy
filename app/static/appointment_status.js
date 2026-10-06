(() => {
  // Pending request pages have no unsaved scheduling form. Refresh only while
  // visible; confirmation renders without this script and stops refreshing.
  window.setInterval(() => {
    if (!document.hidden) window.location.reload();
  }, 15000);
})();

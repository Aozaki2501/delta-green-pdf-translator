async (page) => {
  const outputDir = "Workspace/projects/project001_NewAge高保真HTML修正/02_working/browser_all";
  const pages = page.locator(".typeset-page");
  const count = await pages.count();
  for (let index = 0; index < count; index += 1) {
    await pages.nth(index).screenshot({
      path: `${outputDir}/page_${String(index + 1).padStart(3, "0")}.png`,
      scale: "css",
    });
  }
  return count;
}

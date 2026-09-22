/* Lab fixture behaviour. Deliberately trivial — its job is to make the page feel like a real app
   (and to prove the overlay suppresses the page's own click handlers while inspect is armed). */
(function () {
  "use strict";

  var buttons = document.querySelectorAll(".btn");
  Array.prototype.forEach.call(buttons, function (button) {
    button.addEventListener("click", function () {
      var label = (button.textContent || "").trim();
      console.info("[demo-app] clicked:", label);
      button.animate(
        [{ transform: "scale(1)" }, { transform: "scale(.97)" }, { transform: "scale(1)" }],
        { duration: 160, easing: "ease-out" }
      );
    });
  });

  // Smooth in-page anchors, the way a real landing page would.
  document.addEventListener("click", function (event) {
    var link = event.target && event.target.closest ? event.target.closest('a[href^="#"]') : null;
    if (!link) { return; }
    var id = link.getAttribute("href").slice(1);
    var target = id ? document.getElementById(id) : null;
    if (!target) { return; }
    event.preventDefault();
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
})();

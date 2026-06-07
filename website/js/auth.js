(function () {
  var PASSWORD = 'melon';
  var COOKIE_NAME = 'luna_preview';

  function getCookie(name) {
    var m = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
    return m ? m[2] : null;
  }

  function setCookie(name, val, days) {
    var d = new Date();
    d.setTime(d.getTime() + days * 86400000);
    document.cookie = name + '=' + val + ';expires=' + d.toUTCString() + ';path=/';
  }

  var wall = document.getElementById('auth-wall');
  var content = document.getElementById('page-content');
  if (!wall || !content) return;

  if (getCookie(COOKIE_NAME) === '1') {
    wall.style.display = 'none';
    content.classList.add('visible');
    return;
  }

  document.getElementById('auth-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var input = document.getElementById('auth-password');
    if (input.value === PASSWORD) {
      setCookie(COOKIE_NAME, '1', 30);
      wall.style.display = 'none';
      content.classList.add('visible');
    } else {
      document.getElementById('auth-error').style.display = 'block';
      input.value = '';
      input.focus();
    }
  });
})();

/* Hamburger toggle */
document.addEventListener('DOMContentLoaded', function () {
  var btn = document.querySelector('.nav-hamburger');
  var links = document.querySelector('.nav-links');
  if (btn && links) {
    btn.addEventListener('click', function () {
      links.classList.toggle('open');
    });
  }

  /* FAQ accordion */
  document.querySelectorAll('.faq-question').forEach(function (q) {
    q.addEventListener('click', function () {
      this.parentElement.classList.toggle('open');
    });
  });
});

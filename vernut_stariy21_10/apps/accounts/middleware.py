from django.shortcuts import redirect


class OnboardingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.needs_onboarding():
            path = request.path
            allowed = (
                path.startswith("/app/onboarding")
                or path.startswith("/login")
                or path.startswith("/logout")
                or path.startswith("/app/language")
                or path.startswith("/static")
                or path.startswith("/media")
                or path.startswith("/a/")
            )
            if not allowed:
                return redirect("web:onboarding")
        return self.get_response(request)

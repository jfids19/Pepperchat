import os
import threading
import time

LESSON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lessons')
CONTINUE_PHRASE = "no more questions"

class LessonStep:
    def __init__(self, number, text):
        self.number = number
        self.text = text

class Lesson:
    def __init__(self, title, trigger, steps):
        self.title = title
        self.trigger = trigger.lower().strip()
        self.steps = steps

def load_lessons():
    lessons = []
    if not os.path.isdir(LESSON_DIR):
        return lessons
    for filename in os.listdir(LESSON_DIR):
        if filename.endswith('.txt'):
            filepath = os.path.join(LESSON_DIR, filename)
            with open(filepath, encoding='utf-8') as f:
                content = f.read()
            title = ""
            trigger = ""
            steps = []
            lines = content.split('\n')
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if line.startswith('LESSON_TITLE:'):
                    title = line.replace('LESSON_TITLE:', '').strip()
                elif line.startswith('LESSON_TRIGGER:'):
                    trigger = line.replace('LESSON_TRIGGER:', '').strip()
                elif line.startswith('STEP_') and line.endswith(':'):
                    step_num = int(line.replace('STEP_', '').replace(':', ''))
                    i += 1
                    step_text = ""
                    while i < len(lines):
                        next_line = lines[i].strip()
                        if next_line.startswith('STEP_') or next_line.startswith('END_LESSON') or next_line.startswith('LESSON_'):
                            i -= 1
                            break
                        if next_line:
                            step_text += (" " if step_text else "") + next_line
                        i += 1
                    if step_text:
                        steps.append(LessonStep(step_num, step_text))
                i += 1
            if title and trigger and steps:
                lessons.append(Lesson(title, trigger, steps))
    return lessons

class LessonEngine:
    def __init__(self, speak_callback, listen_mode_callback):
        self.speak = speak_callback
        self.set_normal_chat = listen_mode_callback
        self.lessons = load_lessons()
        self.active_lesson = None
        self.current_step = 0
        self.waiting_for_continue = False
        self._cancelled = False
        self._lock = threading.Lock()
        print(f"LessonEngine loaded {len(self.lessons)} lesson(s):")
        for l in self.lessons:
            print(f"  - '{l.trigger}' -> {l.title}")

    def check_trigger(self, user_text):
        text_lower = user_text.lower().strip()

        # Check for cancel command first
        cancel_phrases = ["cancel lesson", "stop lesson", "lesson cancelled", "cancel the lesson", "stop the lesson", "end lesson", "end the lesson"]
        if any(phrase in text_lower for phrase in cancel_phrases):
            if self.active_lesson or self.waiting_for_continue:
                threading.Thread(target=self.cancel_lesson, daemon=True).start()
                return True

        # Only check continue phrase if a lesson is actually active and not cancelled
        if self.waiting_for_continue and self.active_lesson and not self._cancelled:
            if CONTINUE_PHRASE in text_lower:
                threading.Thread(target=self._next_step, daemon=True).start()
                return True
            else:
                return False

        # Check lesson triggers
        for lesson in self.lessons:
            if lesson.trigger in text_lower:
                threading.Thread(target=self._start_lesson, args=(lesson,), daemon=True).start()
                return True

        return False

    def _start_lesson(self, lesson):
        with self._lock:
            self.active_lesson = lesson
            self.current_step = 0
            self.waiting_for_continue = False
            self._cancelled = False
        print(f"Starting lesson: {lesson.title}")
        self.set_normal_chat(False)
        intro = f"Starting the {lesson.title}. Let's begin!"
        self.speak(intro)
        time.sleep(6)
        if not self._cancelled:
            self._deliver_step()

    def _deliver_step(self):
        with self._lock:
            if self._cancelled or not self.active_lesson:
                return
            if self.current_step >= len(self.active_lesson.steps):
                self._end_lesson()
                return
            step = self.active_lesson.steps[self.current_step]
        print(f"Delivering step {step.number}")
        if self._cancelled:
            return
        self.speak(step.text)
        with self._lock:
            if not self._cancelled:
                self.waiting_for_continue = True
        if not self._cancelled:
            self.set_normal_chat(True)

    def _next_step(self):
        with self._lock:
            if self._cancelled:
                return
            self.current_step += 1
            self.waiting_for_continue = False
        self.set_normal_chat(False)
        if self._cancelled:
            return
        self.speak("Okay, let's move on.")
        time.sleep(4)
        if not self._cancelled:
            self._deliver_step()

    def _end_lesson(self):
        with self._lock:
            self.active_lesson = None
            self.waiting_for_continue = False
            self._cancelled = False
        self.set_normal_chat(True)
        print("Lesson complete.")

    def is_lesson_active(self):
        return self.active_lesson is not None

    def cancel_lesson(self):
        with self._lock:
            self._cancelled = True
            self.active_lesson = None
            self.waiting_for_continue = False
            self.current_step = 0
        self.set_normal_chat(True)
        print("Lesson cancelled.")
        # Keep cancelled flag true for 10 seconds to stop any in-flight threads
        def reset_cancelled():
            time.sleep(10)
            with self._lock:
                self._cancelled = False
        threading.Thread(target=reset_cancelled, daemon=True).start()

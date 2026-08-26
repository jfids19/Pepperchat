# -*- coding: utf-8 -*-

###########################################################
# The GPT-3 OpenAI chatbot class definition. Executes a local
# text based chatbot interface using the GPT-3 chatbot. 
#
# Syntax:
#    python3 openaichat.py
#
# Author: Erik Billing, University of Skovde
# Created: June 2022. 
# License: Copyright reserved to the author. 
###########################################################
import os, sys, codecs, json
from datetime import datetime
from threading import Thread
from oaichat.oairesponse import OaiResponse

import dotenv
dotenv.load_dotenv()

if sys.version_info[0] < 3:
    raise ImportError('OpenAI Chat requires Python 3')

from openai import OpenAI

class OaiChat:
  def __init__(self,user,prompt=None):
    self.log = None
    self.reset(user,prompt)
    self.client = OpenAI(
      base_url="https://api.groq.com/openai/v1",
      api_key=os.getenv('GROQ_API_KEY')
    )

  def reset(self,user,prompt=None):
    self.user = user
    self.history = self.loadPrompt(prompt or os.getenv('OPENAI_PROMPTFILE'))
    self.resetRequestLog()

  def resetRequestLog(self):
    pass

  def respond(self, inputText):
    start = datetime.now()
    self.moderation = None
    self.history.append({'role':'user','content':inputText})

    response = None
    try:
      response = self.client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=self.history,
        max_tokens=150,
      )
    except Exception as ex:
      print("Failed response attempt, trying fallback")
    if not response:
      response = self.client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=self.history,
        max_tokens=150,
      )

    r = OaiResponse(response.model_dump_json())
    self.history.append({'role':'assistant','content':r.getText()})
    print('Request delay',datetime.now()-start)
    return r

  def loadPrompt(self,promptFile):
    promptFile = promptFile or 'openai.prompt'
    promptPath = promptFile if os.path.isfile(promptFile) else os.path.join(os.path.dirname(__file__),promptFile)
    prompt = []
    if not os.path.isfile(promptPath):
      print('WARNING: Unable to locate OpenAI prompt file',promptFile)
    else:
      print('Using prompt file:',promptPath)
      with codecs.open(promptPath,encoding='utf-8') as f:
        prompt.append({'role':'system','content':f.read()})
    return prompt

if __name__ == '__main__':
  chat = OaiChat()
  while True:
    try:
      s = input('> ')
    except KeyboardInterrupt:
      break
    if s:
      print(chat.history)
      print(chat.respond(s).getText())
    else:
      break
  print('Closing GPT Server')

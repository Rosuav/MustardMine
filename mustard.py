from flask import Flask, render_template, g, Markup, request, redirect
import config # Local config variables and passwords, not in source control
app = Flask(__name__)

@app.route("/")
def mainpage():
	return "Hello, world!"

if __name__ == "__main__":
	import logging
	logging.basicConfig(level=logging.DEBUG)
	app.run(host='0.0.0.0')

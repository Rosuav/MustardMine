function event(selector, ev, func) {
	document.querySelectorAll(selector).forEach(el => el["on" + ev] = func);
}

const setupform = document.forms.setups.elements;
const schedform = document.forms.schedule.elements;

function render_setups() {
	const html = setups.map((s, i) => `
		<tr onclick="pick_setup(${i})">
			<td>${s.category}</td>
			<td>${s.title}</td>
			<td>${s.communities.join(", ")}</td>
			<td>${s.tweet}</td>
			<td><button class="deleting" id="del${i}" onclick="try_delete_setup(${i})">X</button></td>
		</tr>
	`);
	document.getElementById("setups").innerHTML =
		"<tr><th>Category</th><th>Title</th><th>Communities</th><th>Tweet</th></tr>" +
		html.join("");
}

function pick_setup(i) {
	const setup = setups[i];
	if (!setup) return; //Shouldn't happen
	setupform.category.value = setup.category;
	setupform.title.value = setup.title;
	setup.communities.forEach((c, i) => setupform["comm"+(i+1)].value = c);
	document.getElementById("tweet").value = setup.tweet;
}

let deleting_setup = -1;
let delete_time = 0;
function try_delete_setup(i) {
	if (deleting_setup != i) {
		//Await confirmation via a second click
		document.querySelectorAll(".deleting").forEach(b => b.innerHTML = "X");
		document.getElementById("del" + i).innerHTML = "Delete?";
		deleting_setup = i;
		delete_time = +new Date + 1;
		return;
	}
	if (+new Date < delete_time) return;
	//Okay, let's actually delete it.
	deleting_setup = -1;
	document.getElementById("del" + i).innerHTML = "X";
	delete_setup(setups[i].id);
}

document.getElementById("hello").onclick = async function() {
	const result = await (await fetch("/api/hello", {credentials: "include"})).json();
	console.log(result);
}

document.getElementById("save").onclick = async function() {
	const result = await (await fetch("/api/setups", {
		credentials: "include",
		headers: {"Content-Type": "application/json"},
		method: "POST",
		body: JSON.stringify({
			category: setupform.category.value,
			title: setupform.title.value,
			communities: [
				setupform.comm1.value,
				setupform.comm2.value,
				setupform.comm3.value,
			].filter(x=>x), //Remove any blank communities
			tweet: document.getElementById("tweet").value,
		})
	})).json();
	setups.push(result);
	render_setups();
}

async function delete_setup(i) {
	const result = await fetch("/api/setups/" + i, {
		credentials: "include",
		method: "DELETE",
	});
	if (!result.ok) return;
	setups = await (await fetch("/api/setups", {credentials: "include"})).json();
	render_setups();
}

function tidy_times(times) {
	return times.replace(",", " ").split(" ").map(tm => {
		//Reformat tm tidily
		//TODO: If tm is exactly "AM" or "PM" (case insensitively),
		//apply the transformation to the previous entry, and discard
		//this one. That will allow "9 pm" to parse correctly.
		//Yes, that's "?::" in a regex. Don't you just LOVE it when a
		//character is sometimes special, sometimes literal?
		//I'm abusing regex a little here; the last bit really should be
		//(AM|PM)?, but there's no way to say "but which of the alternation
		//did you match?". So by splitting it into two matchable parts, I
		//take advantage of the regex case-insensitivity flag. That DOES
		//mean that "2:30AMPM" will match. Simple rule: PM wins. (Just ask
		//Jim Hacker if you don't believe me. Except when he's PM.)
		const parts = /^([0-9][0-9]?)(?::([0-9][0-9]?))?(AM)?(PM)?$/i.exec(tm);
		if (!parts) return "";
		let hour = parseInt(parts[1], 10);
		let min = parseInt(parts[2] || "00", 10);
		if (parts[3] || parts[4]) //AM or PM was set
		{
			if (hour == 12) hour = 0;
			if (parts[4]) hour += 12; //PM
		}
		return ("0" + hour).slice(-2) + ":" + ("0" + min).slice(-2);
	}).join(" ");
}

event(".sched", "change", function() {
	this.value = tidy_times(this.value);
});

setupform.category.value = channel.game;
setupform.title.value = channel.status;
communities.forEach((c, i) => setupform["comm"+(i+1)].value = c);
render_setups();

const local_tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
if (sched_tz === "") {
	//No saved TZ - assume you probably want the one you're using in the browser.
	schedform.sched_tz.value = local_tz;
} else {
	schedform.sched_tz.value = sched_tz;
	if (sched_tz !== local_tz) {
		//Your saved timezone and your browser timezone are different.
		//Notify the user.
		document.getElementById("othertz").innerHTML = "(Your browser's preferred timezone is: " + local_tz + ")";
	}
}

document.getElementById("checklist").innerHTML = checklist.split("\n")
	.map(item => item && "<li><label><input type=checkbox>" + item + "</label></li>")
	.join("");

schedule.forEach((times, day) => schedform["sched" + day].value = tidy_times(times));

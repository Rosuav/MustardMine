const form = document.forms[0].elements;
form.category.value = channel.game;
form.title.value = channel.status;
communities.forEach((c, i) => form["comm"+(i+1)].value = c);
render_setups();

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
	form.category.value = setup.category;
	form.title.value = setup.title;
	setup.communities.forEach((c, i) => form["comm"+(i+1)].value = c);
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

async function hello() {
	const result = await (await fetch("/api/hello", {credentials: "include"})).json();
	console.log(result);
}

async function save() {
	const result = await (await fetch("/api/setups", {
		credentials: "include",
		headers: {"Content-Type": "application/json"},
		method: "POST",
		body: JSON.stringify({
			category: form.category.value,
			title: form.title.value,
			communities: [
				form.comm1.value,
				form.comm2.value,
				form.comm3.value,
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

const local_tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
if (sched_tz === "") {
	//No saved TZ - assume you probably want the one you're using in the browser.
	document.getElementById("sched_tz").value = local_tz;
} else {
	document.getElementById("sched_tz").value = sched_tz;
	if (sched_tz !== local_tz) {
		//Your saved timezone and your browser timezone are different.
		//Notify the user.
		document.getElementById("othertz").innerHTML = "(Your browser's preferred timezone is: " + local_tz + ")";
	}
}

const boxes = checklist.split("\n").map(item => item && "<li><label><input type=checkbox>" + item + "</label></li>");
document.getElementById("checklist").innerHTML = boxes.join("");

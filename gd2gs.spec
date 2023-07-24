Name:		gd2gs
Version:	0.9.0
Release:	%autorelease
Summary:	Get data to Google sheets

License:	GPL-3.0-or-later
URL:		https://github.com/ari3s/gd2gs
Source0:	https://raw.githubusercontent.com/ari3s/gd2gs/main/%{name}-%{version}.tar.gz
BuildArch:	noarch

BuildRequires:	pyproject-rpm-macros
BuildRequires:	python3-devel

%description
gd2gs reads data from the particular source and copies the data in Google
spreadsheet as it is defined in the config file. The config file
also contains relations between the source items and the columns
in Google spreadsheet.

%prep
%autosetup -p1

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files %{name}

%check
%pyproject_check_import

%files -f %{pyproject_files}
%doc README.md
%license COPYING
%{_bindir}/%{name}

%changelog
%autochangelog
